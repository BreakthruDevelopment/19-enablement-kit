---
name: trace-call
description: Use when following a request from a servlet or JSP through an EJB to the DAO. Quotes each hop and stops at a file that was not read.
---

# Trace a call

1. Start at the page or servlet the question names. Quote the call it makes.
2. Open the class it calls. Quote the method. Then the next hop.
3. Read the descriptor when the class relies on one, and quote the element.
4. Stop when the next file is one you have not opened, and say that.
5. Do not propose a rewrite. The trace is the deliverable.
