---
name: review-dao
description: Use when reading or changing a JDBC DAO. Quotes the SQL and flags a statement built by joining strings, without rewriting it unless asked.
---

# Review a DAO

1. Read `sql/CLAUDE.md` and the path-scoped rule for `sql/**/*.sql`. Read the Java
   rule as well when the DAO is a `.java` file.
2. Quote each statement the method sends.
3. If a statement is built by joining strings, quote that line and say so.
4. Do not rewrite the statement unless the task asks for a change.
5. Do not print a row of data from a live database. This skill reads the source only.
