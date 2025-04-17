import os
import subprocess
import json
import sys
import logging
import requests
import time
import argparse
import shutil
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def set_environment_variables():
    try:
        logging.info("Setting environment variables...")
        os.environ['http_proxy'] = 'http://proxy-dmz.intel.com:912'
        os.environ['https_proxy'] = 'http://proxy-dmz.intel.com:912'
        os.environ['PATH'] = f"/mnt/c/bin/coverity_report_tool/bin/:{os.environ['PATH']}"
        os.environ['PATH'] = f"/mnt/c/bin/coverity/bin/:{os.environ['PATH']}"
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

        # Preserve the original indentation
        original_line = lines[line_number - 1]
        leading_spaces = len(original_line) - len(original_line.lstrip())
        indented_fix_value = ' ' * leading_spaces + fix_value + '\n'

        # Replace the line with the suggested fix
        lines[line_number - 1] = indented_fix_value

        # Write the updated content back to the file
        with open(file_path, 'w') as file:
            file.writelines(lines)

        logging.info(f"Replaced line {line_number} in {file_path} with suggestion fix.")

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

        # Move the untracked files and folders to the original-scan-result folder
        for file in untracked_files:
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

def create_github_review(repo, pr_number, token, comments):
    try:
        url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/reviews"
        headers = {
            'Authorization': f'token {token}',
            'Accept': 'application/vnd.github.v3+json'
        }
        data = {
            'body': 'Suggested changes based on Coverity analysis',
            'event': 'COMMENT',
            'comments': comments
        }
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        logging.info(f"Created review for PR #{pr_number}")
    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to create GitHub review: {e}")

def main():
    parser = argparse.ArgumentParser(description='Coverity Analysis Script')
    parser.add_argument('--skip_analysis', action='store_true', help='Skip git cleaning and Coverity commands')
    parser.add_argument('--rerun_count', type=int, default=1, help='Number of times to rerun the script if issues are found')
    parser.add_argument('--scan_scope', choices=['branch', 'repo'], required=True, help='Scope of the scan: branch or repo')
    parser.add_argument('--jira_id', required=True, help='JIRA ID for the commit message prefix')
    parser.add_argument('--github_repo', required=True, help='GitHub repository in the format owner/repo')
    parser.add_argument('--github_token', required=True, help='GitHub token for authentication')
    args = parser.parse_args()

    set_environment_variables()
    # Get access token
    access_token = get_access_token()
    rerun = 0
    modified_files = set()
    
    for rerun in range(args.rerun_count):
        logging.info(f"Scan run count: {rerun}")
        if not args.skip_analysis:
            # Clean up the workspace, skip cleaning the original-scan-result folder if it exists
            logging.info("Cleaning up the workspace...")
            run_command("git clean -xdf -e original-scan-result")
        
        # Run coverity configure command
        logging.info("Running coverity configure command...")
        run_command("cov-configure --config coverity_config/coverity.xml --template --compiler gcc --comptype gcc")
        
        # Run coverity build
        logging.info("Running coverity build...")
        run_command("cov-build --config coverity_config/coverity.xml --dir idir make")
        
        # List files found for coverity analysis
        logging.info("Listing files found for coverity analysis...")
        run_command("cov-manage-emit --dir idir list")
        
        # Perform coverity analysis
        logging.info("Performing coverity analysis...")
        run_command("cov-analyze --dir idir --concurrency --security --rule --enable-constraint-fpp --enable-fnptr --enable-virtual")
        
        # Create coverity reports
        logging.info("Creating coverity reports (JSON)...")
        run_command("cov-format-errors --dir idir --json-output-v9 local_report.json")
        logging.info("Creating coverity reports (Text)...")
        run_command("cov-format-errors --dir idir --text-output-style oneline > local_report.txt")
    
        # Read and format issues from the JSON report
        logging.info("Reading and formatting issues from the JSON report...")
        formatted_issues = read_and_format_issues('local_report.json')
        if formatted_issues:
            for issue in formatted_issues:
                logging.info(issue)
                file_path, line_number, *_ = issue.split(':')
                line_number = int(line_number)
                line_content = get_line_from_file(file_path, line_number)
                if line_content:
                    logging.info(f"Line {line_number} from {file_path}: {line_content}")

                    # Handle scan_scope
                    if args.scan_scope == 'branch':
                        # Collect the lines changed from the base branch
                        result = subprocess.run("git diff $(git merge-base HEAD origin/main) HEAD", shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
                        changed_lines = result.stdout.splitlines()
                        issue_line = f"{file_path}:{line_number}"
                        if issue_line not in changed_lines:
                            logging.info("The issue found is not from the current branch.")
                            continue

                    # Define the prompt template and parameters
                    prompt_template = """
                    Issue: {issue}
                    Code with issue: {code_with_issue}
                    Read the Coverity issue report and the code_with_issue. Act on the following:
                    1. Generate a precise fix code snippet for fixing the issue while maintaining the original code style and indentation.
                    2. Keep the fix relevant to the existing code without making assumptions beyond the provided context.
                    3. Output should follow the structured JSON format with 'fix',
                    4.  Do not add unnecessary information. example: fix: "int x = 0; // Initialize x to 0 to avoid undefined behavior" 
                    5. Validate the generated JSON output to ensure correctness and proper formatting. Verify indentation and structure consistency and do not introduce unrelated changes.
                    """
                    prompt_input = prompt_template.format(issue=issue, code_with_issue=line_content)
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
                    replace_suggested_fix(file_path, line_number, fix_value)
                    modified_files.add(file_path)
        else:
            logging.info("No issues found in the JSON report.")
            break

        # Move untracked files and folders to original-scan-result folder only for the first result
        if modified_files and rerun == 0:
            move_untracked_files()
            # Handle scan_scope
            if args.scan_scope == 'repo':
                current_branch = get_current_branch()
                if not current_branch.startswith('scan-assistant-'):
                    new_branch_name = f"scan-assistant-{datetime.now().strftime('%Y%m%d%H%M%S')}"
                    create_new_branch(new_branch_name)

    # Commit and push changes after all reruns are completed
    if args.scan_scope == 'repo':
        current_branch = get_current_branch()
        logging.info("Current branch to be pushed: %s", current_branch)
        logging.info("Changes done in files: %s", modified_files)
        if modified_files:
            commit_and_push_changes(args.jira_id, current_branch, modified_files)
    elif args.scan_scope == 'branch':
        logging.info("Changes done in files: %s", modified_files)
        if modified_files:
            # Get open PRs for the current branch
            current_branch = get_current_branch()
            prs = get_github_prs(args.github_repo, current_branch, args.github_token)
            if prs:
                pr_number = prs[0]['number']
                comments = []
                for file_path in modified_files:
                    with open(file_path, 'r') as file:
                        lines = file.readlines()
                    for line_number, line_content in enumerate(lines, start=1):
                        if line_content.strip() in [fix_value.strip() for fix_value in modified_files]:
                            comments.append({
                                'path': file_path,
                                'position': line_number,
                                'body': f"Suggested fix for Coverity issue: {line_content.strip()}"
                            })
                create_github_review(args.github_repo, pr_number, args.github_token, comments)
            else:
                logging.info("No PRs found to submit suggestions.")

if __name__ == "__main__":
    main()