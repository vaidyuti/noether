# Coverage Exceptions

Every `# pragma: no cover` in the codebase MUST be listed here with
justification, per ADR-0003. Reviewers reject unlisted pragmas.

| File / pattern | Justification |
| --- | --- |
| `if TYPE_CHECKING:` blocks | Never executed at runtime by definition |

(nothing else yet)
