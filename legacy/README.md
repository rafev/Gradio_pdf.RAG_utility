> **Legacy.** These are the original single-PDF Gradio apps, kept for reference. The current system is the agentic RAG described in the [top-level README](../README.md).
> `qabot.py` uses IBM watsonx.ai + Chroma, `Huggingface_RAG.py` uses local Mistral-7B + FAISS, and `test.py` is a CUDA check.

# Gradio RAG utility for single pdf files
This script will generate a simple Retrieval-Augmented Generation (RAG) web application for single pdf documents via Gradio. 

**Note:** This script was developed in an online notebook environment with a set license for IBM's Watsonx.ai. The user should change the ```project_id``` in within the ```get_llm``` and ```watsonx_embedding``` functions to include their own project id.
