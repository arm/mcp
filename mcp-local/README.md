# FastMCP Learning Path Vector Search Server

This project provides a Model Context Protocol (MCP) server that enables semantic search over a set of learning resources using FAISS and SentenceTransformers embeddings.

It is a remote server that deploys to AWS via AWS CDK.

## Features

- **learning_path_search**: Finds learning resources relevant to a text query using semantic similarity.
- Fast, local search using [FAISS](https://github.com/facebookresearch/faiss) and [all-MiniLM-L6-v2](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2) embeddings.
- Deduplicates results by URL.
- Returns titles, snippets, and URLs for matched resources.
