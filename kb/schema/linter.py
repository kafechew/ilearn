import os
import re
import json
from pathlib import Path

WIKI_DIR = Path("kb/wiki")
SCHEMA_FILE = Path("kb/schema/schema.json")

def clean_name(name):
    # Match Obsidian filename normalization logic
    return name.strip().lower().replace(" ", "_").replace("[", "").replace("]", "")

def run_graph_audit():
    with open(SCHEMA_FILE) as f:
        schema = json.load(f)
        
    all_files = {}
    all_links = {}
    
    # 1. Map existing files
    for root, _, files in os.walk(WIKI_DIR):
        for file in files:
            if file.endswith(".md") and file != "logs.md" and file != "CoreIndex.md":
                path = Path(root) / file
                norm_name = file.replace(".md", "")
                all_files[norm_name] = path
                all_links[norm_name] = []

    dead_links = []
    
    # 2. Extract outbound link definitions
    for name, path in all_files.items():
        content = path.read_text()
        # Regex to locate standard Obsidian wiki links
        links = re.findall(r"\[\[(.*?)\]\]", content)
        for link in links:
            # Handle display pipes gracefully: [[target_file|Display Label]]
            target = clean_name(link.split("|")[0])
            if target not in all_files:
                dead_links.append((name, link))
            else:
                all_links[target].append(name)

    # 3. Filter orphan systems
    orphans = [name for name, incoming in all_links.items() if len(incoming) == 0]

    # Display Report
    print("## 📊 KGT Knowledge Graph Diagnostic Report\n")
    print(f"**Total Tracked System Nodes:** {len(all_files)}")
    
    print("\n### ❌ Dead Link Anomalies")
    for source, target in dead_links:
        print(f"- `{source}.md` references non-existent node: `[[{target}]]`")
        
    print("\n### 🏝️ Orphaned Nodes (Lonely Notes)")
    for orphan in orphans:
        print(f"- `{orphan}.md` has zero inbound connections.")

if __name__ == "__main__":
    run_graph_audit()