# Project rules for the Java EE modernisation

The project's own written rules, applied by the project-rules pass. These are house rules for the
Harbor OMS move off the EJB container; a finding must cite one of them and not a preference.

## RUL-1 | major | No new EJBs, entity beans or JNDI lookups
New code does not add session or entity beans, home or remote interfaces, or `InitialContext`
lookups. Collaborators are constructor-injected plain classes, and a `DataSource` is passed in.

## RUL-2 | major | Database access uses PreparedStatement with bound parameters
Every query goes through `PreparedStatement` (or the project's query helper) with `?` placeholders.
Statement text is never built from a request value. The same rule is a security criterion; both
passes may report a breach and consolidation merges them.

## RUL-3 | major | Errors are logged through SLF4J and surfaced, not swallowed
A caught exception is logged with the logger, passing the exception, and is either rethrown as a
typed exception or reported to the caller. `printStackTrace`, `System.out` and `System.err` are not
used, and a catch block never returns as though nothing went wrong.

## RUL-4 | major | New code uses the jakarta namespaces
New imports use `jakarta.*` and not `javax.*` for Java EE APIs. JDK packages that live under
`javax` (`javax.sql`, `javax.crypto`, `javax.net`) are not covered by this rule.

## RUL-5 | major | REST resources return DTO records, not persistence types
A resource method returns a record or value class made for the response. It never returns an
entity, a `ResultSet` row object or a type from the persistence layer.

## RUL-6 | minor | Business rules do not live in resource classes
A resource class parses the request, calls a service and returns. Filtering, rounding, paging and
other rules belong in the service so they can be tested without HTTP.

## RUL-7 | minor | Public types and methods state their behaviour in Javadoc
A new public class, record or method has a Javadoc comment that says what it does, including what it
returns for an empty result and when it throws.
