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
import sys
from contextlib import ExitStack as does_not_raise

import pytest

from tests.unit.test_general import _test_materializer


@pytest.mark.skipif(
    sys.version_info.major == 3 and sys.version_info.minor == 7,
    reason="Langchain (used by llama_index) is only supported on Python>3.7",
)
def test_llama_index_document_materializer(clean_client):
    """Tests whether the steps work for the Llama Index Document
    materializer."""
    from langchain.docstore.document import Document as LCDocument
    from llama_index.readers.schema.base import Document

    from zenml.integrations.llama_index.materializers.document_materializer import (
        LlamaIndexDocumentMaterializer,
    )

    page_content = (
        "Axl, Aria and Blupus were very cold during the winter months."
    )
    with does_not_raise():
        langchain_document = _test_materializer(
            step_output=Document(text=page_content),
            materializer_class=LlamaIndexDocumentMaterializer,
        )

    assert langchain_document.get_type() == "Document"
    assert langchain_document.text == page_content
    assert isinstance(langchain_document.to_langchain_format(), LCDocument)
