import os
import subprocess
import json
import sys
import logging
import requests
import time
import argparse
import shutil
import yaml
from datetime import datetime
import pandas as pd

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Get the absolute path of the current script
script_dir = os.path.dirname(os.path.abspath(__file__))

def set_environment_variables():
    try:
        logging.info("Setting environment variables...")
        os.environ['http_proxy'] = 'http://proxy-dmz.intel.com:912'
        os.environ['https_proxy'] = 'http://proxy-dmz.intel.com:912'
        os.environ['PATH'] = f"/mnt/c/bin/coverity_report_tool/bin/:/mnt/c/bin/coverity/bin/:{os.environ['PATH']}"
        logging.info("Environment variables set.")
    except Exception as e:
        logging.error(f"Error setting environment variables: {e}")
        sys.exit(1)

def run_command(command):
    try:
        logging.info(f"Running command: {command}")
        result = subprocess.run(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        if result.returncode != 0:
            logging.error(f"Error running command: {command}")
            logging.error(result.stderr)
            sys.exit(1)
        else:
            logging.info(result.stdout)
        return result
    except Exception as e:
        logging.error(f"Exception occurred while running command: {command}")
        logging.error(e)
        sys.exit(1)

def get_access_token():
    client_id = os.getenv('CLIENT_ID')
    client_secret = os.getenv('CLIENT_SECRET')
    if not client_id or not client_secret:
        logging.error("CLIENT_ID and CLIENT_SECRET environment variables must be set.")
        sys.exit(1)

    data = {
        'grant_type': 'client_credentials'
    }
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded'
    }
    try:
        response = requests.post(
            "https://apis.intel.com/v1/auth/token",
            data=data,
            headers=headers,
            auth=(client_id, client_secret),
            proxies=None
        )
        response.raise_for_status()
        response_json = response.json()
        logging.debug("%s", response_json)
        access_token_expires_on = int(response_json.get('expires_in')) + time.time() - 60
        access_token = response_json.get('access_token')
        if not access_token:
            logging.error("Failed to obtain access token.")
            sys.exit(1)
        logging.info("Access token obtained.")
        return access_token
    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to get access token: {e}")
        sys.exit(1)

def read_and_format_issues(json_report_file):
    try:
        with open(json_report_file, 'r') as file:
            data = json.load(file)
            issues = data.get('issues', [])
            if not issues:
                logging.info("No issues found in the JSON report.")
                return []

            formatted_issues = []
            for issue in issues:
                file_path = issue.get('mainEventFilePathname')
                line_number = issue.get('mainEventLineNumber')
                issue_type = issue.get('checkerName')
                language = issue.get('language')
                events = issue.get('events', [])
                event_descriptions = []
                for event in events:
                    description = event.get('eventDescription')
                    if event.get('remediation') == True:
                        description = f"Recommended_Remediation: {description}"
                    event_descriptions.append(description)
                formatted_issue = f"{file_path}:{line_number}:{issue_type}:{language}:{' '.join(event_descriptions)}"
                formatted_issues.append(formatted_issue)
            return formatted_issues
    except Exception as e:
        logging.error(f"Error reading and formatting issues: {e}")
        sys.exit(1)

def get_line_from_file(file_path, line_number):
    try:
        with open(file_path, 'r') as file:
            lines = file.readlines()
            if line_number <= len(lines):
                return lines[line_number - 1].strip()
            else:
                logging.error(f"Line number {line_number} exceeds the number of lines in {file_path}")
                return None
    except Exception as e:
        logging.error(f"Error reading line {line_number} from file {file_path}: {e}")
        return None

def call_gpt_api(access_token, prompt_input):
    api_url = "https://apis.intel.com/generativeaiinference/v2"
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }
    data = {
        "options": {
            "temperature": 1,
            "top_p": 0.95,
            "frequency_penalty": 0,
            "presence_penalty": 0,
            "max_tokens": 1000,
            "stop": None,
            "allowmodelfallback": True,
            "includeConversation": True,
            "model": "gpt-4o"
        },
        "correlationId": "inference-test0905-2",
        "conversation": [
            {
                "role": "system",
                "content": prompt_input
            }
        ]
    }
    try:
        response = requests.post(api_url, headers=headers, json=data)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to call GPT API: {e}")
        sys.exit(1)

def replace_suggested_fix(file_path, line_number, fix_value):
    try:
        # Read the file content
        with open(file_path, 'r') as file:
            lines = file.readlines()

        # Get the original line
        original_line = lines[line_number - 1]
        leading_spaces = len(original_line) - len(original_line.lstrip())  # Calculate leading spaces

        # Apply the same indentation to the suggested fix
        indented_fix_lines = [' ' * leading_spaces + line for line in fix_value.split('\n')]

        # Replace the original line with the indented suggested fix
        lines[line_number - 1] = '\n'.join(indented_fix_lines) + '\n'

        # Write the updated content back to the file
        with open(file_path, 'w') as file:
            file.writelines(lines)

        logging.info(f"Replaced line {line_number} in {file_path} with suggested fix.")

        # Check if this is a git workspace and print the new changes
        if os.path.isdir(os.path.join(os.path.dirname(file_path), '.git')):
            logging.info("Printing new changes in the file using git command:")
            run_command(f"git diff {file_path}")

    except Exception as e:
        logging.error(f"Error replacing suggested fix in {file_path}: {e}")

def move_untracked_files():
    try:
        # Create the folder named original-scan-result
        os.makedirs('original-scan-result', exist_ok=True)

        # Get the list of untracked files and folders
        result = subprocess.run("git ls-files --others --exclude-standard", shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        untracked_files = result.stdout.splitlines()

        # Move the untracked files and folders to the original-scan-result folder, excluding copilot_data.json
        for file in untracked_files:
            if file == 'copilot_data.json':
                continue
            destination = os.path.join('original-scan-result', os.path.basename(file))
            if os.path.isdir(file):
                if os.path.exists(destination):
                    shutil.rmtree(destination)
                shutil.move(file, destination)
            else:
                if os.path.exists(destination):
                    os.remove(destination)
                shutil.move(file, destination)

        logging.info("Moved untracked files and folders to original-scan-result folder.")
    except Exception as e:
        logging.error(f"Error moving untracked files: {e}")

def get_current_branch():
    try:
        result = subprocess.run("git rev-parse --abbrev-ref HEAD", shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        if result.returncode != 0:
            logging.error(f"Error getting current branch: {result.stderr}")
            sys.exit(1)
        return result.stdout.strip()
    except Exception as e:
        logging.error(f"Exception occurred while getting current branch: {e}")
        sys.exit(1)

def create_new_branch(branch_name):
    try:
        run_command(f"git checkout -b {branch_name}")
    except Exception as e:
        logging.error(f"Error creating new branch {branch_name}: {e}")
        sys.exit(1)

def commit_and_push_changes(jira_id, branch_name, modified_files):
    try:
        for file in modified_files:
            run_command(f"git add {file}")
        run_command(f"git commit -m '{jira_id}: Applied suggested fixes'")
        run_command(f"git push origin {branch_name}")
    except Exception as e:
        logging.error(f"Error committing and pushing changes: {e}")
        sys.exit(1)

def get_github_prs(repo, branch, token):
    try:
        url = f"https://api.github.com/repos/{repo}/pulls"
        headers = {
            'Authorization': f'token {token}',
            'Accept': 'application/vnd.github.v3+json'
        }
        params = {
            'head': branch,
            'state': 'open'
        }
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to get GitHub PRs: {e}")
        return []

def create_github_review(repo, pr_number, token, comments, body):
    """
    Creates a GitHub review for a pull request.

    Args:
        repo (str): The repository in the format 'owner/repo'.
        pr_number (int): The pull request number.
        token (str): The GitHub token for authentication.
        comments (list): A list of comments to add to the review.
        body (str): The body of the review.

    Returns:
        None
    """
    try:
        url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/reviews"
        headers = {
            'Authorization': f'token {token}',
            'Accept': 'application/vnd.github.v3+json'
        }
        data = {
            'body': body,
            'event': 'COMMENT',
            'comments': comments
        }
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        logging.info(f"Created review for PR #{pr_number}")
    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to create GitHub review: {e}")

def create_pull_request(repo, token, title, head, base, body):
    try:
        url = f"https://api.github.com/repos/{repo}/pulls"
        headers = {
            'Authorization': f'token {token}',
            'Accept': 'application/vnd.github+json'
        }
        data = {
            'title': title,
            'head': head,
            'base': base,
            'body': body
        }
        logging.info(f"Creating pull request from {head} to {base} with data: {data}")
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        pr = response.json()
        logging.info(f"Created pull request #{pr['number']}")
        return pr['number']
    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to create pull request: {e}")
        return None

def load_coverity_commands(language):
    try:
        coverity_commands_path = os.path.join(script_dir, 'coverity_commands.yaml')
        with open(coverity_commands_path, 'r') as file:
            commands = yaml.safe_load(file)
            return commands.get(language, [])
    except Exception as e:
        logging.error(f"Error loading Coverity commands: {e}")
        sys.exit(1)

def get_base_branch():
    try:
        result = subprocess.run("git symbolic-ref --short HEAD", shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        if result.returncode != 0:
            logging.error(f"Error getting base branch: {result.stderr}")
            sys.exit(1)
        return result.stdout.strip()
    except Exception as e:
        logging.error(f"Exception occurred while getting base branch: {e}")
        sys.exit(1)

def setup_update_workspace(branch, json_file_path, rerun):
    # Clean up the workspace, skip cleaning the original-scan-result folder and JSON file if it exists
    logging.info("Cleaning up the workspace...")
    run_command(f"git clean -xdf -e original-scan-result -e {json_file_path}")
    
    # Stash untracked files
    run_command("git stash push -m 'Stash untracked files' --include-untracked")
    
    # Reset the workspace content to the base branch content
    run_command(f"git checkout -- .")
    run_command(f"git checkout {branch}")
    
    # Apply the stash to restore untracked files
    run_command("git stash pop")
    
    # Apply suggested fixes from JSON file
    # json_file_path = os.path.join('original-scan-result', 'copilot_data.json') if rerun > 0 else 'copilot_data.json'
    with open(json_file_path, 'r+') as json_file:
        json_data = json.load(json_file)
        for json_issue in json_data["issues"]:
            if json_issue["copilot_fixed"] == "true":
                file_path = json_issue["file_name"]
                line_number = json_issue["line_number"]
                suggested_fix = json_issue["suggested_fix"]
                replace_suggested_fix(file_path, line_number, suggested_fix)

def generate_summary_table(json_data):
    issues = json_data.get("issues", [])
    summary_data = []
    for issue in issues:
        summary_data.append({
            "Line No": issue["line_number"],
            "File": issue["file_name"],
            "Issue code": issue["issue"],
            "Fix suggested by copilot": "Yes" if issue["copilot_fixed"] == "true" else "No"
        })
    df = pd.DataFrame(summary_data)
    return df.to_markdown(index=False)

# Add this function to check if there is any suggested fix to apply
def has_suggested_fixes(json_file_path):
    try:
        with open(json_file_path, 'r') as json_file:
            json_data = json.load(json_file)
            for issue in json_data.get("issues", []):
                if issue.get("copilot_fixed") == "true":
                    return True
        return False
    except Exception as e:
        logging.error(f"Error checking for suggested fixes in {json_file_path}: {e}")
        sys.exit(1)

def get_pr_modified_files(repo, pr_number, token):
    try:
        logging.info(f"Fetching modified files for PR #{pr_number} in repository {repo}...")
        url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/files"
        headers = {
            'Authorization': f'token {token}',
            'Accept': 'application/vnd.github.v3+json'
        }
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        files = response.json()
        logging.debug(f"Response from GitHub API: {json.dumps(files, indent=4)}")

        modified_files = {}
        for file in files:
            file_path = file["filename"]
            logging.info(f"Processing file: {file_path}, status: {file['status']}")
            if file["status"] == "added":
                # For added files, include the entire file
                modified_files[file_path] = []
            elif file["status"] == "modified":
                modified_lines = []
                if "patch" in file:
                    # Extract modified line numbers from the patch
                    for line in file["patch"].split("\n"):
                        if line.startswith("@@"):
                            # Extract line numbers from the hunk header
                            hunk_info = line.split(" ")[1]
                            start_line = int(hunk_info.split(",")[0].replace("+", ""))
                            line_count = int(hunk_info.split(",")[1]) if "," in hunk_info else 1
                            modified_lines.extend(range(start_line, start_line + line_count))
                            logging.debug(f"Extracted modified lines: {modified_lines}")
                modified_files[file_path] = modified_lines
        logging.info(f"Modified files and lines: {modified_files}")
        return modified_files
    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to fetch PR modified files: {e}")
        return {}

def get_relative_path(file_path, repo_root):
    """
    Strips the system path and returns the relative path from the repository root.
    """
    if file_path.startswith(repo_root):
        return file_path[len(repo_root):].lstrip("/")
    return file_path

def generate_report_table(json_file_path, start_time, repo_name):
    try:
        with open(json_file_path, 'r') as json_file:
            json_data = json.load(json_file)
            issues = json_data.get("issues", [])
            total_issues = len(issues)
            resolved_issues = sum(1 for issue in issues if issue.get("copilot_fixed") == "true")
            unresolved_issues = total_issues - resolved_issues
            resolution_percentage = (resolved_issues / total_issues * 100) if total_issues > 0 else 0
            execution_time = time.time() - start_time

            # Prepare the report table
            report_data = [
                ["Repository", repo_name],
                ["Total Issues Found", total_issues],
                ["Issues Resolved by AI", resolved_issues],
                ["% of Issues Resolved", f"{resolution_percentage:.2f}%"],
                ["Time Taken (seconds)", f"{execution_time:.2f}"]
            ]

            # Format the table
            report_table = "\n".join([f"{row[0]:<30}: {row[1]}" for row in report_data])
            return report_table
    except Exception as e:
        logging.error(f"Error generating report table: {e}")
        return None

def main():
    parser = argparse.ArgumentParser(description='Coverity Analysis Script')
    parser.add_argument('--skip_analysis', action='store_true', help='Skip git cleaning and Coverity commands')
    parser.add_argument('--rerun_count', type=int, default=1, help='Number of times to rerun the script if issues are found')
    parser.add_argument('--scan_scope', choices=['pr', 'repo'], required=True, help='Scope of the scan: pr or repo')
    parser.add_argument('--jira_id', required=True, help='JIRA ID for the commit message prefix')
    parser.add_argument('--github_repo', required=True, help='GitHub repository in the format owner/repo')
    parser.add_argument('--pr_number', type=int, help='Pull Request number (required if scan_scope is pr)')
    parser.add_argument('--language', required=True, help='Programming language for Coverity analysis')
    args = parser.parse_args()

    # Initialize variables
    start_time = time.time()
    pr_number = None  # Initialize pr_number to None

    if args.scan_scope == 'pr' and not args.pr_number:
        parser.error("--pr_number is required when scan_scope is 'pr'")
    pr_number = args.pr_number  # Set pr_number from args
    logging.info(f"PR number: {pr_number}")

    set_environment_variables()
    # Get access token
    github_token = os.getenv('GH_TOKEN')
    if not github_token:
        logging.error("GH_TOKEN environment variable must be set.")
        sys.exit(1)

    access_token = get_access_token()
    rerun = 0
    modified_files = set()
    new_branch_name = f"copilot-scan-{datetime.now().strftime('%Y%m%d%H%M%S')}"

    coverity_commands = load_coverity_commands(args.language)

    # Read base branch from workspace
    base_branch = get_base_branch()

    # Initialize JSON file
    json_file_path = 'copilot_data.json'
    if rerun == 0 and not args.skip_analysis:
        with open(json_file_path, 'w') as json_file:
            json.dump({"base_branch": base_branch, "issues": []}, json_file)

    if not args.skip_analysis:
        for rerun in range(args.rerun_count):
            logging.info(f"Scan run count: {rerun}")
            setup_update_workspace(base_branch, json_file_path, rerun)

            # Run Coverity commands
            for command in coverity_commands:
                run_command(command)

            # Read and format issues from the JSON report
            logging.info("Reading and formatting issues from the JSON report...")
            formatted_issues = read_and_format_issues('local_report.json')
            if formatted_issues:
                for issue in formatted_issues:
                    logging.info(issue)
                    file_path, line_number, *_ = issue.split(':')
                    line_number = int(line_number)
                    line_content = get_line_from_file(file_path, line_number)
                    rerun_fix = ""  # Initialize rerun_fix with a default value
                    with open(json_file_path, 'r') as json_file:
                        json_data = json.load(json_file)
                        for json_issue in json_data["issues"]:
                            if json_issue["file_name"] == file_path and json_issue["line_number"] == line_number:
                                if json_issue["copilot_fixed"] == "false":
                                    rerun_fix = f"This suggested_fix {json_issue['suggested_fix']} does not solve the issue. Provide an alternate fix."
                                    break
                    if line_content:
                        logging.info(f"Line {line_number} from {file_path}: {line_content}")

                        # Define the prompt template and parameters
                        prompt_template = """
                        Issue: {issue}
                        Code with issue: {code_with_issue}
                        {rerun_fix}
                        Read the Coverity issue report and the code_with_issue. Act on the following:
                        1. Generate a precise fix code snippet for fixing the issue while maintaining the original code style and indentation.
                        2. Keep the fix relevant to the existing code without making assumptions beyond the provided context.
                        3. Output should follow the structured JSON format with 'fix',
                        4. Do not add unnecessary information. example: fix: "int x = 0; // Initialize x to 0 to avoid undefined behavior"
                        5. The code must be functional and compilable in case of langauges that needs compilations
                        6. Validate the generated JSON output to ensure correctness and proper formatting. Verify indentation and structure consistency and do not introduce unrelated changes.
                        """
                        prompt_input = prompt_template.format(issue=issue, code_with_issue=line_content, rerun_fix=rerun_fix)
                        prompt_input = f'"{prompt_input}"'
                        logging.info(f"Prompt input: {prompt_input}")

                        # Call the GPT API
                        gpt_response = call_gpt_api(access_token, prompt_input)
                        logging.info("GPT API response:")
                        logging.info(json.dumps(gpt_response, indent=4))
                        currentResponse = gpt_response.get('currentResponse')
                        logging.info(f"Suggestion fix: %s", currentResponse)
                        currentResponse = currentResponse.strip('```json\n').strip('\n```')
                        data = json.loads(currentResponse)
                        fix_value = data["fix"]
                        logging.info(fix_value)

                        # Update JSON file with issue details
                        with open(json_file_path, 'r+') as json_file:
                            json_data = json.load(json_file)
                            if rerun == 0:
                                json_data["issues"].append({
                                    "issue": issue,
                                    "file_name": file_path,
                                    "line_number": line_number,
                                    "code_with_issue": line_content,
                                    "suggested_fix": fix_value,
                                    "copilot_fixed": "true"
                                })
                                modified_files.add(file_path)  # Add file_path to modified_files
                            else:
                                for json_issue in json_data["issues"]:
                                    if json_issue["file_name"] == file_path and json_issue["line_number"] == line_number:
                                        if json_issue["suggested_fix"] == line_content:
                                            json_issue["copilot_fixed"] = "false"
                                            break
                            json_file.seek(0)
                            json.dump(json_data, json_file, indent=4)
                    else:
                        logging.error(f"Error reading line {line_number} from {file_path}")
                        break
            else:
                logging.info("No new issues found in this scan run.")
                break

            # Move untracked files and folders to original-scan-result folder only for the first result
            if modified_files and rerun == 0:
                move_untracked_files()
                if args.scan_scope == 'repo':
                    current_branch = get_current_branch()
                    if not current_branch.startswith('copilot-scan-'):
                        create_new_branch(new_branch_name)

    # Commit and push changes after all reruns are completed
    if args.scan_scope == 'repo' and modified_files:
        # Check if there are any suggested fixes to apply
        if not has_suggested_fixes(json_file_path):
            logging.info("No fixes suggested by Copilot. Exiting the script.")
            sys.exit(0)

        logging.info("Current branch: %s", current_branch)
        logging.info("Changes done in files: %s", modified_files)
        # Ensure the workspace is ready with all updates for the upload
        setup_update_workspace(new_branch_name, json_file_path, rerun)
        current_branch = get_current_branch()
        if current_branch.startswith('copilot-scan-'):
            commit_and_push_changes(args.jira_id, current_branch, modified_files)
        # Create a pull request after pushing changes
        pr_number = create_pull_request(
            repo=f"{args.github_repo}",
            token=f"{github_token}",
            title=f"{args.jira_id}: Coverity fix from copilot scan",
            head=current_branch,
            base="main",  # Replace with the base branch name
            body="This PR contains the suggested fixes for Coverity issues."
        )
    elif args.scan_scope == 'pr':
        modified_files = set()
        with open(json_file_path, 'r') as json_file:
            json_data = json.load(json_file)
            for issue in json_data.get("issues", []):
                if issue.get("copilot_fixed") == "true":
                    modified_files.add(issue.get("file_name"))
        logging.info("Changes done in files: %s", modified_files)
        if modified_files:
            # Fetch modified files and lines in the PR
            pr_modified_files = get_pr_modified_files(args.github_repo, pr_number, github_token)
            logging.info("Modified files in the PR:")
            logging.info(pr_modified_files)
            if not pr_modified_files:
                logging.info("No modified files found in the PR.")
                return

            # Determine the repository root path
            repo_root = os.path.commonpath([os.getcwd()])

            # Read copilot_data.json
            with open(json_file_path, 'r') as json_file:
                json_data = json.load(json_file)

            comments = []
            for issue in json_data.get("issues", []):
                absolute_file_name = issue["file_name"]  # Absolute path
                logging.info(f"Absolute file name: {absolute_file_name}")
                relative_file_name = os.path.relpath(absolute_file_name, repo_root)  # Convert to relative path
                logging.info(f"Relative file name: {relative_file_name}")
                line_number = issue["line_number"]
                suggested_fix = issue["suggested_fix"]

                # Normalize paths for comparison
                relative_file_name = relative_file_name.replace("\\", "/")  # Ensure consistent path separators
                logging.info(f"Normalized relative file name: {relative_file_name}")
                for pr_file, pr_lines in pr_modified_files.items():
                    if not pr_lines:  # Handle newly added files
                        pr_lines = list(range(1, len(open(pr_file).readlines()) + 1))
                    if relative_file_name == pr_file and line_number in pr_lines:
                        # Preserve the original indentation of the line
                        original_line = open(pr_file).readlines()[line_number - 1]
                        leading_spaces = len(original_line) - len(original_line.lstrip())
                        indented_fix_lines = [' ' * leading_spaces + line for line in suggested_fix.split('\n')]

                        # Format the suggestion with proper indentation
                        formatted_suggestion = '\n'.join(indented_fix_lines)

                        comments.append({
                            'path': pr_file,
                            'position': pr_lines.index(line_number) + 1,  # Position in the diff
                            'body': f"Suggested fix:\n```suggestion\n{formatted_suggestion}\n```"
                        })

            # Add comments to the PR
            logging.info("Comments to be added to the PR:")
            logging.info(comments)
            if comments and not args.skip_analysis:
                review_body = "Suggested changes based on Coverity analysis"
                create_github_review(args.github_repo, args.pr_number, github_token, comments, review_body)
            else:
                logging.info("No matching issues found for the PR.")

    else:
        logging.info("No changes found in the workspace to push or add suggestion to PR.")

    repo_name = args.github_repo.split("/")[-1]  # Extract the repository name
    report_table = generate_report_table(json_file_path, start_time, repo_name)

    # Enhance the report table to include detailed issue information
    try:
        with open(json_file_path, 'r') as json_file:
            json_data = json.load(json_file)
            issues = json_data.get("issues", [])
            detailed_data = []
            for idx, issue in enumerate(issues, start=1):
                issue_parts = issue['issue'].split(':')
                file_line = f"{issue_parts[0]}:{issue_parts[1]}"
                issue_id = issue_parts[2]
                file_line = f"{issue['file_name']}:{issue['line_number']}"
                status = "Fix suggested" if issue.get("copilot_fixed") == "true" else "Unable to Fix"
                suggested_fix = f"[View Suggestion](https://github.com/{args.github_repo}/pull/{args.pr_number}#discussion_r{issue.get('pr_comment_id', 'None')})" if issue.get("pr_comment_id") else "None"
                detailed_data.append({
                    "Issue Id": issue_id,
                    "File:Line Number": file_line,
                    "Agent verdict": status
                })
            df = pd.DataFrame(detailed_data)
            detailed_report_table = df.to_markdown(index=False)
            report_table += "\n\nDetailed Issue Report:\n" + detailed_report_table
    except Exception as e:
        logging.error(f"Error generating detailed issue report: {e}")
    if report_table:
        logging.info("\nExecution Report:\n" + report_table)
        # Add the report table as a comment to the PR
        if pr_number:
            logging.info(f"Adding report table to PR #{pr_number}")
            create_github_review(
                repo=args.github_repo,
                pr_number=pr_number,
                token=github_token,
                comments=[],
                body=f"Coverity AI Agent Execution Report:\n\n```\n{report_table}\n```"
            )

if __name__ == "__main__":
    main()