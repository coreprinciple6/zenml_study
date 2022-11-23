#  Copyright (c) ZenML GmbH 2022. All Rights Reserved.
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
"""Models representing stack components."""

from typing import Any, Dict

from pydantic import BaseModel, Field, validator

from zenml.enums import StackComponentType
from zenml.logger import get_logger
from zenml.models.base_models import (
    ShareableRequestModel,
    ShareableResponseModel,
    update,
)
from zenml.models.constants import MODEL_NAME_FIELD_MAX_LENGTH
from zenml.utils import secret_utils

logger = get_logger(__name__)

# TODO: Add example schemas and analytics fields


# ---- #
# BASE #
# ---- #
class ComponentBaseModel(BaseModel):
    """Base model for stack components."""

    name: str = Field(
        title="The name of the stack component.",
        max_length=MODEL_NAME_FIELD_MAX_LENGTH,
    )
    type: StackComponentType = Field(
        title="The type of the stack component.",
    )

    flavor: str = Field(
        title="The flavor of the stack component.",
    )

    configuration: Dict[str, Any] = Field(
        title="The stack component configuration.",
    )


# -------- #
# RESPONSE #
# -------- #


class ComponentResponseModel(ComponentBaseModel, ShareableResponseModel):
    """Response model for stack components."""


# ------- #
# REQUEST #
# ------- #


class ComponentRequestModel(ComponentBaseModel, ShareableRequestModel):
    """Request model for stack components."""

    @validator("name")
    def name_cant_be_a_secret_reference(cls, name):
        if secret_utils.is_secret_reference(name):
            raise ValueError(
                "Passing the `name` attribute of a stack component as a "
                "secret reference is not allowed."
            )
        return name


# ------ #
# UPDATE #
# ------ #


@update
class ComponentUpdateModel(ComponentRequestModel):
    """Update model for stack components."""
