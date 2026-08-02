#!/usr/bin/env python3
"""
HR Policy Assistant
RAG pipeline over the company employee handbook stored in IBM Db2.
Retrieves exact policy sections before answering — cites leave days, dates, and approvals.

Setup:
    pip install haystack-ai haystack-integrations
    ollama pull granite-embedding:278m && ollama pull granite3.3:8b
    export DB2_USERNAME=db2inst1 DB2_PASSWORD=secret DB2_HOST=localhost
"""

import os
from haystack import Pipeline
from haystack.utils import Secret
from haystack.components.builders import PromptBuilder
from haystack_integrations.document_stores.ibm_db import IBMDb2DocumentStore
from haystack_integrations.components.embedders.ollama import OllamaTextEmbedder
from haystack_integrations.components.retrievers.ibm_db import IBMDb2EmbeddingRetriever
from haystack_integrations.components.generators.ollama import OllamaGenerator

# Db2 vector table — must be pre-populated by an ingestion pipeline
document_store = IBMDb2DocumentStore(
    database="HR_DB",
    hostname=os.environ.get("DB2_HOST", "localhost"),
    port=50000,
    username=Secret.from_env_var("DB2_USERNAME"),  # Secret keeps credentials out of logs
    password=Secret.from_env_var("DB2_PASSWORD"),
    table_name="employee_handbook",
    embedding_dim=768,          # must match the embedding model's output dimension
    distance_metric="COSINE",   # cosine similarity is standard for sentence embeddings
)

pipeline = Pipeline()

# Prefix is required by Granite for asymmetric (query vs passage) retrieval
pipeline.add_component("embedder", OllamaTextEmbedder(
    model="granite-embedding:278m",
    url=os.environ.get("OLLAMA_URL", "http://localhost:11434"),
    prefix="Represent this sentence for searching relevant passages: ",
))

pipeline.add_component("retriever", IBMDb2EmbeddingRetriever(document_store=document_store, top_k=3))

pipeline.add_component("prompt_builder", PromptBuilder(template="""\
You are an HR Policy Assistant. Answer using ONLY the policies below.
Cite exact numbers, dates, and approval requirements.
If not covered, say: "Please contact HR at hr@company.com"

Question: {{ question }}
Context:{% for doc in documents %}
- {{ doc.content }}{% endfor %}
"""))

pipeline.add_component("llm", OllamaGenerator(
    model="granite3.3:8b",
    url=os.environ.get("OLLAMA_URL", "http://localhost:11434"),
))

# Wire: question → embed → retrieve → prompt → generate
pipeline.connect("embedder.embedding",    "retriever.query_embedding")
pipeline.connect("retriever.documents",   "prompt_builder.documents")
pipeline.connect("prompt_builder.prompt", "llm.prompt")

QUESTION = "How many annual leave days do employees receive?"
result = pipeline.run(
    {"embedder": {"text": QUESTION}, "prompt_builder": {"question": QUESTION}},
    include_outputs_from={"retriever"},  # expose retrieved docs for debugging
)

print(f"\nQ: {QUESTION}")
print(f"A: {result['llm']['replies'][0]}\n")  # OllamaGenerator returns plain strings

for doc in result["retriever"]["documents"]:
    print(f"  [{doc.score:.3f}]  {doc.content[:80]}…")
