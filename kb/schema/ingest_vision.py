import os
import sys
from pathlib import Path
from openai import OpenAI
from markitdown import MarkItDown

# Custom utility to explicitly force load a local .env file 
def load_env_file():
    env_path = Path(".env")
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.strip() and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ[key.strip()] = val.strip()

def process_visual_document(input_path_str):
    # Ensure local environment configurations are fully loaded
    load_env_file()
    
    input_path = Path(input_path_str)
    output_path = input_path.with_suffix(".md")

    # Fetch your configured token
    gemini_key = os.environ.get("GEMINI_API_KEY")
    if not gemini_key:
        print("Error: Missing GEMINI_API_KEY environment parameter inside your .env configuration.")
        sys.exit(1)

    print(f"Initializing Gemini-Powered Multimodal Extraction Pipeline for: {input_path.name}...")

    # Route through Gemini's official OpenAI-compatible endpoint bridge
    # Ref: https://ai.google.dev/gemini-api/docs/openai
    client = OpenAI(
        api_key=gemini_key,
        base_url="https://googleapis.com"
    )

    # Initialize MarkItDown leveraging the Google endpoint mapping channel
    md = MarkItDown(
        enable_plugins=True, 
        llm_client=client, 
        llm_model="gemini-3.1-flash-lite" # Set your targeted low-latency model
    )

    try:
        # Execute the multimodal extraction sequence
        result = md.convert(str(input_path))
        
        # Output clean markdown text assets
        output_path.write_text(result.text_content)
        print(f"Success! Gemini-powered extraction compiled down into: {output_path}")
        
    except Exception as e:
        print(f"Execution Error during structural conversion sequence: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python ingest_vision.py <path_to_file>")
        sys.exit(1)
    process_visual_document(sys.argv[1])
