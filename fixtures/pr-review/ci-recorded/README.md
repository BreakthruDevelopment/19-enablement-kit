# Recorded replies for the default CI run

`kit-review.yml` runs `kit review-ci` over every pull request's diff. With no secret and no label it
uses these: one clean recording per finding pass, so a recorded run never quotes text that is not in
the diff (which would reject the pass and post `blocking`). They prove the pipeline ran and nothing
more, and the report says so. Consolidation has no file: a run with no findings never reaches it.
