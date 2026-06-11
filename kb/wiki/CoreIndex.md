# 🧠 Intelligence Brain Index

```dataview
TABLE 
  type as "Node Type", 
  links as "Outgoing Connections",
  file.mtime as "Last Updated"
FROM "01_entities" OR "02_concepts" OR "03_clusters"
SORT file.name ASC
```

### 📈 Global Knowledge Base Audit Logs
```dataview
LIST FROM "logs"
```