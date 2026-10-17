"""Public-text check mutations (#216, #221, #229).

Each mutant removes one part of the ref-update sweep, the tag sweep, the
bounded listings they read, the reporting of a cancelled scan, or the refusal
of a redirect. Only
assertion failures count as kills.
"""

from _mutations import run

MODULE = "scripts.ci.check_public_text:"
TESTS = "tests/test_public_text_check.py::"
OLD_DATED = TESTS + "test_an_old_dated_commit_pushed_after_the_cursor_is_scanned"
BRANCHES = TESTS + "test_new_and_deleted_branches_and_the_default_branch_creation_are_covered"
PAGES = TESTS + "test_activity_cursor_pages_are_followed_and_the_period_widens_with_the_window"
FAILS = TESTS + "test_every_ref_update_failure_fails_closed"
TAGS = TESTS + "test_every_tag_is_scanned_in_full"
STOPPED = TESTS + "test_a_scan_stopped_by_a_base_exception_still_reports_what_it_found"
SIGNALS = TESTS + "test_the_runner_signals_end_the_scan_as_cancelled_after_its_findings"

MUTANTS = (
    ("ref updates are read", MODULE + "sweep",
     "yield from pushed(github, since_time, now, default(), seen)", "yield from ()", OLD_DATED),
    ("one failing surface does not hide the rest", MODULE + "sweep",
     "failures.append(error)", "raise",
     TESTS + "test_a_failing_surface_does_not_hide_the_rest"),
    ("commits dated in the window stay a second source", MODULE + "sweep",
     'github.pages(f"commits?sha={name}&since={since}")', "iter(())",
     TESTS + "test_sweep_covers_commits_comments_reviews_and_updated_pull_requests"),
    ("a push is compared from its previous head", MODULE + "pushed",
     "commits = compared(github, before, after)", "commits = compared(github, default, after)",
     OLD_DATED),
    ("updates before the cursor are not compared", MODULE + "pushed",
     'if utc(str(update["timestamp"])) < since_time:', "if False:", OLD_DATED),
    ("a deletion exposes no commit", MODULE + "pushed",
     "if after == NO_COMMIT:", "if False:", BRANCHES),
    ("the default branch's creation lists its whole history", MODULE + "pushed",
     "elif branch == default:", "elif False:", BRANCHES),
    ("a new branch is compared with the default branch", MODULE + "pushed",
     "commits = compared(github, default, after)", "commits = iter(())", BRANCHES),
    ("every updated ref's name is scanned", MODULE + "pushed",
     'yield ("branch name" if branch != ref else "ref name"), _digest(branch), branch', "pass",
     BRANCHES),
    ("the activity period widens with the window", MODULE + "pushed",
     "if elapsed <= span", "if True", PAGES),
    ("an update that names no commit is refused", MODULE + "_sha",
     "if not isinstance(value, str) or not SHA.fullmatch(value):", "if False:",
     FAILS + "[malformed head]"),
    ("comparison pages are followed", MODULE + "compared",
     "if len(listed) < 100:", "if True:",
     TESTS + "test_comparison_pages_are_followed_and_their_declared_count_met"),
    ("a comparison's declared count is met", MODULE + "compared",
     "count != total", "False", FAILS + "[short comparison]"),
    ("a comparison is page-bounded", MODULE + "compared",
     'raise Incomplete("comparison exceeds the page bound")', "pass",
     FAILS + "[endless comparison]"),
    ("a linked listing follows its next link", MODULE + "GitHub.linked",
     "if following is None:", "if True:", PAGES),
    ("a linked listing stays in the API", MODULE + "GitHub.linked",
     'if not url.startswith(f"{API}/"):', "if False:", FAILS + "[link outside the API]"),
    ("a page without headers is refused", MODULE + "GitHub.linked",
     "if headers is None or not isinstance(items, list):", "if not isinstance(items, list):",
     FAILS + "[page without headers]"),
    ("a later page must keep its links", MODULE + "GitHub.linked",
     "if page and not link:", "if False:", FAILS + "[later page without links]"),
    ("a full page without a next link is refused", MODULE + "GitHub.linked",
     "if len(items) >= 100:", "if False:", FAILS + "[full page without next]"),
    ("a linked listing is page-bounded", MODULE + "GitHub.linked",
     'raise Incomplete("listing exceeds the page bound")', "pass",
     FAILS + "[endless activity]"),
    ("tags are swept", MODULE + "sweep",
     "yield from tagged(github, default(), seen)", "yield from ()", TAGS),
    ("tag names are scanned", MODULE + "tagged",
     'yield "tag name", _digest(name), name', "pass", TAGS),
    ("an annotated tag's own name is scanned", MODULE + "tagged",
     'str(annotated.get("tag") or ""), ', "", TAGS),
    ("annotated tags are followed", MODULE + "tagged",
     'if named.get("type") != "tag":', "if True:", TAGS),
    ("a tag's commits off the default branch are scanned", MODULE + "tagged",
     'yield from _unseen(github, commits, "tag", seen)', "pass", TAGS),
    ("a tag must reach a commit", MODULE + "tagged",
     'if named.get("type") != "commit":', "if False:",
     TESTS + "test_a_tag_that_reaches_no_commit_fails_closed[blob]"),
    ("a stop that is not an Exception is reported", MODULE + "main",
     "except BaseException as error:", "except Exception as error:", STOPPED),
    ("findings are printed as they are made", MODULE + "main",
     "findings(items, compiled, found, _report)", "findings(items, compiled, found)", STOPPED),
    ("the runner's signals end the scan", MODULE + "main",
     "previous[number] = signal.signal(number, _cancel)",
     "previous[number] = signal.getsignal(number)", SIGNALS + "[SIGTERM]"),
    ("a cancellation ignores the runner's next signal", MODULE + "_cancel",
     "signal.signal(number, signal.SIG_IGN)", "pass",
     TESTS + "test_a_cancellation_ignores_the_runners_next_signal"),
    ("a redirect is refused, so the token stays with the API", MODULE + "open_api",
     "urllib.request.build_opener(_NoRedirect)", "urllib.request.build_opener()",
     TESTS + "test_a_redirect_is_refused_and_the_token_never_reaches_its_target[302]"),
    ("the previous signal handlers are restored", MODULE + "main",
     "signal.signal(number, signal.SIG_DFL if handler is None else handler)", "pass",
     SIGNALS + "[SIGINT]"),
)


if __name__ == "__main__":
    raise SystemExit(run(MUTANTS))
