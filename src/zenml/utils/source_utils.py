#  Copyright (c) ZenML GmbH 2023. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at:
#
#       https://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express
#  or implied. See the License for the specific language governing
#  permissions and limitations under the License.
"""Utilities for loading/resolving objects."""
import contextlib
import importlib
import inspect
import os
import site
import sys
from distutils.sysconfig import get_python_lib
from pathlib import Path, PurePath
from types import FunctionType, ModuleType
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    Iterator,
    Optional,
    Type,
    Union,
    cast,
)

from zenml.config.source import (
    CodeRepositorySource,
    DistributionPackageSource,
    Source,
    SourceType,
)
from zenml.logger import get_logger
from zenml.utils.pagination_utils import depaginate

if TYPE_CHECKING:
    from zenml.code_repositories import (
        BaseCodeRepository,
        LocalRepositoryContext,
    )

logger = get_logger(__name__)


_CODE_REPOSITORY_CACHE: Dict[str, "LocalRepositoryContext"] = {}
_CUSTOM_SOURCE_ROOT: Optional[str] = None


def load(source: Union[Source, str]) -> Any:
    """Load a source or import path.

    Args:
        source: The source to load.

    Returns:
        The loaded object.
    """
    if isinstance(source, str):
        source = Source.from_import_path(source)

    import_root = None
    if source.type == SourceType.CODE_REPOSITORY:
        source = CodeRepositorySource.parse_obj(source)
        _warn_about_potential_source_loading_issues(source=source)
        import_root = get_source_root()
    elif source.type == SourceType.DISTRIBUTION_PACKAGE:
        source = DistributionPackageSource.parse_obj(source)
        if source.version:
            current_package_version = _get_package_version(
                package_name=source.package_name
            )
            if current_package_version != source.version:
                logger.warning(
                    "The currently installed version `%s` of package `%s` "
                    "does not match the source version `%s`. This might lead "
                    "to unexpected behavior when using the source object `%s`.",
                    current_package_version,
                    source.package_name,
                    source.version,
                    source.import_path,
                )
    elif source.type in {SourceType.USER, SourceType.UNKNOWN}:
        # Unknown source might also refer to a user file, include source
        # root in python path just to be sure
        import_root = get_source_root()

    module = _load_module(module_name=source.module, import_root=import_root)

    if source.attribute:
        obj = getattr(module, source.attribute)
    else:
        obj = module

    return obj


def resolve(obj: Union[Type[Any], FunctionType, ModuleType]) -> Source:
    """Resolve an object.

    Args:
        obj: The object to resolve.

    Raises:
        RuntimeError: If the object can't be resolved.

    Returns:
        The source of the resolved object.
    """
    if isinstance(obj, ModuleType):
        module = obj
        attribute_name = None
    else:
        module = sys.modules[obj.__module__]
        attribute_name = obj.__name__

    if attribute_name and getattr(module, attribute_name, None) is not obj:
        raise RuntimeError(
            f"Unable to resolve object `{obj}`. For the resolving to work, the "
            "class or function must be defined as top-level code (= it must "
            "get defined when importing the module) and not inside a function/"
            f"if-condition. Please make sure that your `{module.__name__}` "
            f"module has a top-level attribute `{attribute_name}` that "
            "holds the object you want to resolve."
        )

    module_name = module.__name__
    if module_name == "__main__":
        module_name = _resolve_module(module)

    source_type = get_source_type(module=module)

    if source_type == SourceType.USER:
        local_repo_context = find_active_code_repository()

        if local_repo_context and not local_repo_context.has_local_changes:
            module_name = _resolve_module(module)

            source_root = get_source_root()
            subdir = PurePath(source_root).relative_to(local_repo_context.root)

            return CodeRepositorySource(
                repository_id=local_repo_context.code_repository_id,
                commit=local_repo_context.current_commit,
                subdirectory=subdir.as_posix(),
                module=module_name,
                attribute=attribute_name,
            )

        module_name = _resolve_module(module)
    elif source_type == SourceType.DISTRIBUTION_PACKAGE:
        package_name = _get_package_for_module(module_name=module_name)
        if package_name:
            package_version = _get_package_version(package_name=package_name)
            return DistributionPackageSource(
                module=module_name,
                attribute=attribute_name,
                package_name=package_name,
                version=package_version,
                type=source_type,
            )
        else:
            # Fallback to an unknown source if we can't find the package
            source_type = SourceType.UNKNOWN

    return Source(
        module=module_name, attribute=attribute_name, type=source_type
    )


def get_source_root() -> str:
    """Get the source root.

    The source root will be determined in the following order:
    - The manually specified custom source root if it was set.
    - The ZenML repository directory if one exists in the current working
      directory or any parent directories.
    - The parent directory of the main module file.

    Returns:
        The source root.

    Raises:
        RuntimeError: If the main module file can't be found.
    """
    if _CUSTOM_SOURCE_ROOT:
        logger.debug("Using custom source root: %s", _CUSTOM_SOURCE_ROOT)
        return _CUSTOM_SOURCE_ROOT

    from zenml.client import Client

    repo_root = Client.find_repository()
    if repo_root:
        logger.debug("Using repository root as source root: %s", repo_root)
        return str(repo_root.resolve())

    main_module = sys.modules.get("__main__")
    if main_module is None:
        raise RuntimeError(
            "Unable to determine source root because the main module could not "
            "be found."
        )

    if not hasattr(main_module, "__file__") or not main_module.__file__:
        raise RuntimeError(
            "Unable to determine source root because the main module does not "
            "have an associated file. This could be because you're running in "
            "an interactive Python environment."
        )

    path = Path(main_module.__file__).resolve().parent

    logger.debug("Using main module parent directory as source root: %s", path)
    return str(path)


def set_custom_source_root(source_root: Optional[str]) -> None:
    """Sets a custom source root.

    If set this has the highest priority and will always be used as the source
    root.

    Args:
        source_root: The source root to use.
    """
    logger.debug("Setting custom source root: %s", source_root)
    global _CUSTOM_SOURCE_ROOT
    _CUSTOM_SOURCE_ROOT = source_root


def set_custom_local_repository(
    root: str, commit: str, repo: "BaseCodeRepository"
) -> None:
    """Manually defines a local repository for a path.

    To explain what this function does we need to take a dive into source
    resolving and what happens inside the Docker image entrypoint:
    * When trying to resolve an object to a source, we first determine whether
    the file is a user file or not.
    * If the file is a user file, we check if that user file is inside a clean
    code repository using the `source_utils.find_active_code_repository(...)`
    function. If that is the case, the object will be resolved to a
    `CodeRepositorySource` which includes additional information about the
    current commit and the ID of the code repository.
    * The `source_utils.find_active_code_repository(...)` uses the
    code repository implementation classes to check whether the code repository
    "exists" at that local path. For git repositories, this check might look as
    follows: The code repository first checks if there is a git repository at
    that path or in any parent directory. If there is, the remote URLs of this
    git repository will be checked to see if one matches the URL defined for
    the code repository.
    * When running a step inside a Docker image, ZenML potentially downloads
    files from a code repository. This usually does not download the entire
    repository (and in the case of git might not download a .git directory which
    defines a local git repository) but only specific files. If we now try to
    resolve any object while running in this container, it will not get resolved
    to a `CodeRepositorySource` as
    `source_utils.find_active_code_repository(...)` won't find an active
    repository. As we downloaded these files, we however know that they belong
    to a certain code repository at a specific commit, and that's what we can
    define using this function.

    Args:
        root: The repository root.
        commit: The commit of the repository.
        repo: The code repository associated with the local repository.
    """
    from zenml.utils.downloaded_repository_context import (
        _DownloadedRepositoryContext,
    )

    global _CODE_REPOSITORY_CACHE

    path = os.path.abspath(get_source_root())
    _CODE_REPOSITORY_CACHE[path] = _DownloadedRepositoryContext(
        code_repository_id=repo.id, root=root, commit=commit
    )


def find_active_code_repository(
    path: Optional[str] = None,
) -> Optional["LocalRepositoryContext"]:
    """Find the active code repository for a given path.

    Args:
        path: Path at which to look for the code repository. If not given, the
            source root will be used.

    Returns:
        The local repository context active at that path or None.
    """
    global _CODE_REPOSITORY_CACHE
    from zenml.client import Client
    from zenml.code_repositories import BaseCodeRepository

    path = path or get_source_root()
    path = os.path.abspath(path)

    if path in _CODE_REPOSITORY_CACHE:
        return _CODE_REPOSITORY_CACHE[path]

    for model in depaginate(list_method=Client().list_code_repositories):
        try:
            repo = BaseCodeRepository.from_model(model)
        except Exception:
            logger.debug(
                "Failed to instantiate code repository class.", exc_info=True
            )
            continue

        local_context = repo.get_local_context(path)
        if local_context:
            _CODE_REPOSITORY_CACHE[path] = local_context
            return local_context

    return None


def is_internal_module(module_name: str) -> bool:
    """Checks if a module is internal (=part of the zenml package).

    Args:
        module_name: Name of the module to check.

    Returns:
        True if the module is internal, False otherwise.
    """
    return module_name.split(".", maxsplit=1)[0] == "zenml"


def is_user_file(file_path: str) -> bool:
    """Checks if a file is a user file.

    Args:
        file_path: The file path to check.

    Returns:
        True if the file is a user file, False otherwise.
    """
    source_root = get_source_root()
    return Path(source_root) in Path(file_path).resolve().parents


def is_standard_lib_file(file_path: str) -> bool:
    """Checks if a file belongs to the Python standard library.

    Args:
        file_path: The file path to check.

    Returns:
        True if the file belongs to the Python standard library, False
        otherwise.
    """
    stdlib_root = get_python_lib(standard_lib=True)
    return Path(stdlib_root).resolve() in Path(file_path).resolve().parents


def is_distribution_package_file(file_path: str, module_name: str) -> bool:
    """Checks if a file/module belongs to a distribution package.

    Args:
        file_path: The file path to check.
        module_name: The module name.

    Returns:
        True if the file/module belongs to a distribution package, False
        otherwise.
    """
    absolute_file_path = Path(file_path).resolve()

    for path in site.getsitepackages() + [site.getusersitepackages()]:
        if Path(path).resolve() in absolute_file_path.parents:
            return True

    if _get_package_for_module(module_name=module_name):
        return True

    # TODO: Both of the previous checks don't detect editable installs because
    # the site packages dir only contains a reference to the source files,
    # not the actual files, and importlib_metadata doesn't detect it as a valid
    # distribution package. That means currently editable installs get a
    # source type UNKNOWN which might or might not lead to issues.

    return False


def get_source_type(module: ModuleType) -> SourceType:
    """Get the type of a source.

    Args:
        module: The module for which to get the source type.

    Returns:
        The source type.
    """
    try:
        file_path = inspect.getfile(module)
    except (TypeError, OSError):
        # builtin file
        return SourceType.BUILTIN

    if is_internal_module(module_name=module.__name__):
        return SourceType.INTERNAL

    if is_standard_lib_file(file_path=file_path):
        return SourceType.BUILTIN

    if is_user_file(file_path=file_path):
        return SourceType.USER

    if is_distribution_package_file(
        file_path=file_path, module_name=module.__name__
    ):
        return SourceType.DISTRIBUTION_PACKAGE

    return SourceType.UNKNOWN


@contextlib.contextmanager
def prepend_python_path(path: str) -> Iterator[None]:
    """Context manager to temporarily prepend a path to the python path.

    Args:
        path: Path that will be prepended to sys.path for the duration of
            the context manager.

    Yields:
        None
    """
    try:
        sys.path.insert(0, path)
        yield
    finally:
        sys.path.remove(path)


def _warn_about_potential_source_loading_issues(
    source: CodeRepositorySource,
) -> None:
    """Warn about potential issues when loading the code repository source.

    Args:
        source: The code repository source.
    """
    local_repo = find_active_code_repository()

    if not local_repo:
        logger.warning(
            "Potential issue when loading the source `%s`: The source "
            "references the code repository `%s` which is not active at the "
            "current source root `%s`. The source loading might fail or load "
            "your local code which might differ from the one used when the "
            "source was originally stored.",
            source.import_path,
            source.repository_id,
            get_source_root(),
        )
    elif local_repo.code_repository_id != source.repository_id:
        logger.warning(
            "Potential issue when loading the source `%s`: The source "
            "references the code repository `%s` but there is a different "
            "code repository `%s` active at the current source root `%s`. The "
            "source loading might fail or load "
            "your local code which might differ from the one used when the "
            "source was originally stored.",
            source.import_path,
            source.repository_id,
            local_repo.code_repository_id,
            get_source_root(),
        )
    elif local_repo.current_commit != source.commit:
        logger.warning(
            "Potential issue when loading the source `%s`: The source "
            "references the commit `%s` of code repository `%s` but your local "
            "code is at commit `%s`. The source loading might fail or load "
            "your local code which might differ from the one used when the "
            "source was originally stored.",
            source.import_path,
            source.commit,
            source.repository_id,
            local_repo.current_commit,
        )
    elif local_repo.is_dirty:
        logger.warning(
            "Potential issue when loading the source `%s`: The source "
            "references the commit `%s` of code repository `%s` but your local "
            "repository contains uncommitted changes. The source loading might "
            "fail or load your local code which might differ from the one used "
            "when the source was originally stored.",
            source.import_path,
            source.commit,
            source.repository_id,
        )


def _resolve_module(module: ModuleType) -> str:
    """Resolve a module.

    Args:
        module: The module to resolve.

    Raises:
        RuntimeError: If the module resolving failed.

    Returns:
        The resolved module import path.
    """
    if not hasattr(module, "__file__") or not module.__file__:
        if module.__name__ == "__main__":
            raise RuntimeError(
                f"Unable to resolve module `{module}` because it was "
                "not loaded from a file."
            )
        return module.__name__

    module_file = os.path.abspath(module.__file__)
    source_root = os.path.abspath(get_source_root())

    module_source_path = os.path.relpath(module_file, source_root)

    if module_source_path.startswith(os.pardir):
        raise RuntimeError(
            f"Unable to resolve module `{module}`. The file from which the "
            f"module was loaded ({module_file}) is outside the source root "
            f"({source_root})."
        )

    # Remove the file extension and replace the os-specific path separators
    # with `.` to get the module source
    module_source_path, file_extension = os.path.splitext(module_source_path)
    if file_extension != ".py":
        raise RuntimeError(
            f"Unable to resolve module `{module}`. The file from which the "
            f"module was loaded ({module_file}) is not a python file."
        )

    module_source = module_source_path.replace(os.path.sep, ".")

    logger.debug("Resolved module `%s` to `%s`", module, module_source)

    return module_source


def _load_module(
    module_name: str, import_root: Optional[str] = None
) -> ModuleType:
    """Load a module.

    Args:
        module_name: The name of the module to load.
        import_root: The import root to use for loading the module. If given,
            will be prepended to the Python path before trying to import the
            module.

    Returns:
        The imported module.
    """
    if import_root:
        with prepend_python_path(import_root):
            return importlib.import_module(module_name)
    else:
        return importlib.import_module(module_name)


def _get_package_for_module(module_name: str) -> Optional[str]:
    """Get the package name for a module.

    Args:
        module_name: The module name.

    Returns:
        The package name or None if no package was found.
    """
    if sys.version_info < (3, 10):
        from importlib_metadata import packages_distributions
    else:
        from importlib.metadata import packages_distributions

    top_level_module = module_name.split(".", maxsplit=1)[0]
    package_names = packages_distributions().get(top_level_module, [])

    if len(package_names) == 1:
        return package_names[0]

    # TODO: maybe handle packages which share the same top-level import
    return None


def _get_package_version(package_name: str) -> Optional[str]:
    """Gets the version of a package.

    Args:
        package_name: The name of the package for which to get the version.

    Returns:
        The package version or None if fetching the version failed.
    """
    if sys.version_info < (3, 10):
        from importlib_metadata import PackageNotFoundError, version

        version = cast(Callable[..., str], version)
    else:
        from importlib.metadata import PackageNotFoundError, version

    try:
        return version(distribution_name=package_name)
    except (ValueError, PackageNotFoundError):
        return None


# Ideally both the expected_class and return type should be annotated with a
# type var to indicate that both they represent the same type. However, mypy
# currently doesn't support this for abstract classes:
# https://github.com/python/mypy/issues/4717
def load_and_validate_class(
    source: Union[str, Source], expected_class: Type[Any]
) -> Type[Any]:
    """Loads a source class and validates its class.

    Args:
        source: The source.
        expected_class: The class that the source should resolve to.

    Raises:
        TypeError: If the source does not resolve to the expected class.

    Returns:
        The resolved source class.
    """
    obj = load(source)

    if isinstance(obj, type) and issubclass(obj, expected_class):
        return obj
    else:
        raise TypeError(
            f"Error while loading `{source}`. Expected class "
            f"{expected_class.__name__}, got {obj} instead."
        )


def validate_source_class(
    source: Union[Source, str], expected_class: Type[Any]
) -> bool:
    """Validates that a source resolves to a certain class.

    Args:
        source: The source to validate.
        expected_class: The class that the source should resolve to.

    Returns:
        True if the source resolves to the expected class, False otherwise.
    """
    try:
        obj = load(source)
    except Exception:
        return False

    if isinstance(obj, type) and issubclass(obj, expected_class):
        return True
    else:
        return False
