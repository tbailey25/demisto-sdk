import argparse
import re
import sys

import requests
import urllib3

from demisto_sdk.commands.common.logger import logger

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

JIRA_HOST_FOR_REGEX = r"https:\/\/jira-hq.paloaltonetworks.local\/browse\/"
JIRA_KEY_REGEX = r"([A-Z][A-Z0-9]+-[0-9]+))\s?"
JIRA_FIXED_ISSUE_REGEX = rf"[fF]ixes:\s?.*({JIRA_HOST_FOR_REGEX}{JIRA_KEY_REGEX}"
JIRA_RELATED_ISSUE_REGEX = rf"[rR]elates:\s?.*({JIRA_HOST_FOR_REGEX}{JIRA_KEY_REGEX}"
GENERIC_WEBHOOK_NAME = "GenericWebhook_link_pr_to_jira"


def arguments_handler():
    """Validates and parses script arguments.

    Returns:
       Namespace: Parsed arguments object.

    """
    parser = argparse.ArgumentParser(description="Linking GitHub PR to Jira Issue.")
    parser.add_argument("-l", "--pr_link", help="The PR url.")
    parser.add_argument("-n", "--pr_num", help="The PR number.")
    parser.add_argument("-t", "--pr_title", help="The PR Title.")
    parser.add_argument("-b", "--pr_body", help="The content of the PR description.")
    parser.add_argument(
        "-m",
        "--is_merged",
        help="Boolean. Whether the PR was merged or not.",
        action=argparse.BooleanOptionalAction,  # type: ignore
    )
    parser.add_argument("-u", "--username", help="The instance username.")
    parser.add_argument("-s", "--password", help="The instance password.")
    parser.add_argument("-url", "--url", help="The instance url.")

    return parser.parse_args()


def find_fixed_issue_in_body(body_text, is_merged):
    """
    Getting the issues url in the PR's body as part of `fixing: <issue>` format.
    Return list of issues found: [{"link": link, "id": issue_id}]
    """
    fixed_jira_issues = re.findall(JIRA_FIXED_ISSUE_REGEX, body_text)
    related_jira_issue = re.findall(JIRA_RELATED_ISSUE_REGEX, body_text)
    logger.info(f"Detected {related_jira_issue=}")

    # If a PR is not merged, we just add the pr link to all the linked issues using Gold.
    # If the PR is merged, we only send issues that should be closed by it.
    # Assuming If the PR was merged, all the related links were fetched when the PR last edited.
    fixed_issue = [
        {"link": link, "id": issue_id, "action": "fixes"}
        for link, issue_id in fixed_jira_issues
    ]
    related_issue = []

    if not is_merged:
        logger.info("Not merging, getting related issues.")
        related_issue = [
            {"link": link, "id": issue_id, "action": "relates"}
            for link, issue_id in related_jira_issue
        ]

    return fixed_issue + related_issue


def trigger_generic_webhook(options):
    pr_link = options.pr_link
    pr_title = options.pr_title
    pr_body = options.pr_body
    is_merged = options.is_merged
    pr_num = options.pr_num
    username = options.username
    password = options.password
    instance_url = options.url

    logger.info(f"Detected Pr: {pr_title=}, {pr_link=}, {pr_body=}")

    # Handle cases where the PR did not intend to add links:
    if (
        "fixes:" not in pr_body.lower()
        and "relates:" not in pr_body.lower()
        and "fixed:" not in pr_body.lower()
        and "related:" not in pr_body.lower()
    ):
        logger.info("Did not detect Jira linking pattern.")
        return

    issues_in_pr = find_fixed_issue_in_body(pr_body, is_merged)

    if not issues_in_pr:
        logger.error(
            "ERROR: No linked issues were found in PR. Make sure you correctly linked issues."
        )

        sys.exit(1)

    logger.info(f"found issues in PR: {issues_in_pr}")

    body = {
        "name": f"{GENERIC_WEBHOOK_NAME} - #{pr_num}",
        "raw_json": {
            "PullRequestNum": pr_num,
            "closeIssue": "true"
            if is_merged
            else "false",  # whether to close the fixed issue in Jira
            "PullRequestLink": pr_link,  # will be used to add to jira issue's fields
            "PullRequestTitle": f"[{pr_title}|{pr_link}]",  # will be used in comment of attaching jira issue.
            "JiraIssues": issues_in_pr,
        },
    }
    logger.info(body)
    # post to Content Gold
    res = requests.post(instance_url, json=body, auth=(username, password))

    if res.status_code != 200:
        logger.error(
            f"Trigger playbook for Linking GitHub PR to Jira Issue failed. Post request to Content"
            f" Gold has status code of {res.status_code}"
        )
        sys.exit(1)

    res_json = res.json()
    if res_json and isinstance(res_json, list):
        res_json_response_data = res.json()[0]
        if res_json_response_data:
            investigation_id = res_json_response_data.get("id")
            logger.info(f"{investigation_id=}")


def main():
    options = arguments_handler()
    trigger_generic_webhook(options)


if __name__ == "__main__":
    main()
