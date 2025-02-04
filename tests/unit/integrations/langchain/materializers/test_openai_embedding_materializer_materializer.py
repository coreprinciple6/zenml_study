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
    sys.version_info.major == 3 and sys.version_info.minor <= 7,
    reason="Langchain is only supported on Python >=3.8",
)
def test_langchain_openai_embedding_materializer(clean_client):
    """Tests the Langchain OpenAI Embeddings materializer."""
    from langchain.embeddings import OpenAIEmbeddings

    from zenml.integrations.langchain.materializers.openai_embedding_materializer import (
        LangchainOpenaiEmbeddingMaterializer,
    )

    fake_key = "aria_and_blupus"
    fake_chunk_size = 1234
    fake_model_name = "zenml_best_model"

    with does_not_raise():
        embeddings = _test_materializer(
            step_output=OpenAIEmbeddings(
                chunk_size=fake_chunk_size,
                openai_api_key=fake_key,
                document_model_name=fake_model_name,
            ),
            materializer_class=LangchainOpenaiEmbeddingMaterializer,
        )

    assert embeddings.document_model_name == fake_model_name
    assert embeddings.openai_api_key == fake_key
    assert embeddings.chunk_size == fake_chunk_size
