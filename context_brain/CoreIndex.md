# Index Table

```dataview
TABLE type as "Classification", tags as "Domain Profile"
FROM "01_entities" OR "02_concepts" OR "03_clusters" OR "04_effort_matrices"
SORT file.name ASC
```