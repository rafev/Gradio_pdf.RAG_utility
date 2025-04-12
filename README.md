# Gradio Retreival-Augmented Generation (RAG) utility for pdf files
Ever have a large document that you need summarized, or have proprietary information you need to retrieve quickly? Retrieval-Augmented Generation (RAG) is a form of generative AI that can help. Within this repo there are two scripts to execute a web application for RAG tasks. Both scripts will launch a simple RAG web application for single pdf documents via Gradio. Each script showcases a different use-case, depending on the level of privacy desired. ```qabot.py``` uses an IBM LLM API for fast processing, but runs in IBMs cloud. Should users desire something run locally for privacy concerns, ```Huggingface_RAG.py``` provides that solution, using a medium weight LLM to balance performance and resources.


### qabot.py for Langchain 0.0 versions
```qabot.py``` is the original script using older versions of langchain (0.0 versions) and langchain_community. It uses Chroma as the vector data base and a simmilarity search. The llm framework uses IBM's WatsonX.AI to perform embeddings and interact with the LLM for queries.
**NOTE:** This script was developed in an online notebook environment with a set license for IBM's Watsonx.ai. The user should change the ```project_id``` in within the ```get_llm``` and ```watsonx_embedding``` functions to include their own project id.

### Huggingface_RAG.py for langchain 0.3 and greater
```Huggingface_RAG.py``` is the most recent iteration using HuggingFace as an opensource framework. The model uses ```BAAI/bge-small-en-v1.5``` for document embeddings due to its speed and light weight while performing reasonably well. For the LLM ```Mistral-7B-v0.1``` was chosen for its excellet performance in text-gerneration tasks. FAISS was selected as the vector data base here, and operates with a similarity search.
**NOTE:** ```Mistral-7B-v0.1``` on HuggingFace requires approval to access the repository. Users should login to their HuggingFace account and request permission, then set their API key as an environmental variable named ```Huggingface_write_API_key``` in a .env file for this script to run "out of the box".
