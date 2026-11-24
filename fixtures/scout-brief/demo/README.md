# Demo case for `kit scout`

`replies/brief.json` is one recorded model reply, in app 17's replay format, for a scout run over
`sample/legacy-oms/`. It names the four planted problems, each with the files it is in and a line
quoted from them:

| Problem | Where |
| --- | --- |
| the datasource JNDI lookup repeated in nine classes | nine `*Bean.java` files |
| a transaction declared in `ejb-jar.xml` that `PricingServiceBean` manages itself | `PricingServiceBean.java` |
| SQL built by string concatenation | `OrderDao.findByCustomerAndStatus` |
| one class that is both an HTTP servlet and an EJB writing to the database | `CatalogAdminBean.java` |

    kit scout sample/legacy-oms

The reply's `coverage` is the model's own claim and is **not** what the brief carries: the scout
replaces it with the sandbox's counts and a reason built from fixed codes. Every `evidence_quote`
here must stay verbatim in the sample, and every cited file must be one the scout serves. Editing
the sample means editing the quotes, or the verifier drops the finding.
