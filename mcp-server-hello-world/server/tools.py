"""
Tools module for the MCP server.

This module defines all the tools (functions) that the MCP server exposes to clients.
Tools are the core functionality of an MCP server - they are callable functions that
AI assistants and other clients can invoke to perform specific actions.

Each tool should:
- Have a clear, descriptive name
- Include comprehensive docstrings (used by AI to understand when to call the tool)
- Return structured data (typically dict or list)
- Handle errors gracefully
"""

import requests

from server import utils


def load_tools(mcp_server):
    """
    Register all MCP tools with the server.

    This function is called during server initialization to register all available
    tools with the MCP server instance. Tools are registered using the @mcp_server.tool
    decorator, which makes them available to clients via the MCP protocol.

    Args:
        mcp_server: The FastMCP server instance to register tools with. This is the
                   main server object that handles tool registration and routing.

    Example:
        To add a new tool, define it within this function using the decorator:

        @mcp_server.tool
        def my_new_tool(param: str) -> dict:
            '''Description of what the tool does.'''
            return {"result": f"Processed {param}"}
    """

    @mcp_server.tool
    def health() -> dict:
        """
        Check the health of the MCP server and Databricks connection.

        This is a simple diagnostic tool that confirms the server is running properly.
        It's useful for:
        - Monitoring and health checks
        - Testing the MCP connection
        - Verifying the server is responsive

        Returns:
            dict: A dictionary containing:
                - status (str): The health status ("healthy" if operational)
                - message (str): A human-readable status message

        Example response:
            {
                "status": "healthy",
                "message": "Custom MCP Server is healthy and connected to Databricks Apps."
            }
        """
        return {
            "status": "healthy",
            "message": "Custom MCP Server is healthy and connected to Databricks Apps.",
        }

    @mcp_server.tool
    def get_current_user() -> dict:
        """
        Get information about the current authenticated user.

        This tool retrieves details about the user who is currently authenticated
        with the MCP server. When deployed as a Databricks App, this returns
        information about the end user making the request. When running locally,
        it returns information about the developer's Databricks identity.

        Useful for:
        - Personalizing responses based on the user
        - Authorization checks
        - Audit logging
        - User-specific operations

        Returns:
            dict: A dictionary containing:
                - display_name (str): The user's display name
                - user_name (str): The user's username/email
                - active (bool): Whether the user account is active

        Example response:
            {
                "display_name": "John Doe",
                "user_name": "john.doe@example.com",
                "active": true
            }

        Raises:
            Returns error dict if authentication fails or user info cannot be retrieved.
        """
        try:
            w = utils.get_user_authenticated_workspace_client()
            user = w.current_user.me()
            return {
                "display_name": user.display_name,
                "user_name": user.user_name,
                "active": user.active,
            }
        except Exception as e:
            return {"error": str(e), "message": "Failed to retrieve user information"}

    # ========================================================================
    # Atlassian Jira Tools
    # ========================================================================

    @mcp_server.tool
    def search_jira(query: str, max_results: int = 20) -> dict:
        """
        Search for Jira issues using JQL (Jira Query Language).

        Search across all issues in your Jira instance using powerful query syntax.
        Useful for finding issues by status, type, assignee, labels, or any other field.

        Args:
            query: JQL query string (e.g., "project = PROJ AND status = Open")
            max_results: Maximum number of issues to return (default: 20, max: 100)

        Returns:
            dict: Contains 'issues' list with basic issue details and optional 'error'

        Example queries:
            - "project = PROJ"
            - "assignee = currentUser()"
            - "status = 'In Progress'"
            - "type = Bug AND priority = High"
        """
        try:
            config = utils.get_atlassian_config()
            headers = utils.get_atlassian_auth_header()
            url = f"{config['site_url']}/rest/api/3/search"

            response = requests.get(
                url,
                headers=headers,
                params={"jql": query, "maxResults": min(max_results, 100)},
                timeout=10,
            )
            response.raise_for_status()

            data = response.json()
            issues = []
            for issue in data.get("issues", []):
                issues.append(
                    {
                        "key": issue.get("key"),
                        "summary": issue.get("fields", {}).get("summary"),
                        "status": issue.get("fields", {}).get("status", {}).get("name"),
                        "assignee": issue.get("fields", {})
                        .get("assignee", {})
                        .get("displayName"),
                        "type": issue.get("fields", {}).get("issuetype", {}).get("name"),
                    }
                )

            return {"success": True, "issues": issues, "total": data.get("total")}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp_server.tool
    def list_jira_issues(project_key: str, status: str = "Open") -> dict:
        """
        List Jira issues in a specific project and status.

        Retrieve issues from a project filtered by status. Useful for getting quick
        overviews of project work.

        Args:
            project_key: The project key (e.g., "PROJ")
            status: Filter by status (default: "Open"). Examples: "Open", "In Progress",
                   "Done"

        Returns:
            dict: Contains 'issues' list with issue keys and summaries or 'error'
        """
        try:
            jql = f'project = "{project_key}" AND status = "{status}"'
            return search_jira(jql, max_results=50)
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp_server.tool
    def create_jira_issue(
        project_key: str, issue_type: str, summary: str, description: str = ""
    ) -> dict:
        """
        Create a new Jira issue.

        Create a new issue in the specified project. Use this to automate ticket creation
        from notes, errors, or requests.

        Args:
            project_key: The project key (e.g., "PROJ")
            issue_type: Type of issue (e.g., "Bug", "Task", "Story", "Epic")
            summary: Brief title/summary of the issue
            description: Detailed description (optional)

        Returns:
            dict: Contains 'key' of created issue or 'error'
        """
        try:
            config = utils.get_atlassian_config()
            headers = utils.get_atlassian_auth_header()
            url = f"{config['site_url']}/rest/api/3/issues"

            payload = {
                "fields": {
                    "project": {"key": project_key},
                    "issuetype": {"name": issue_type},
                    "summary": summary,
                    "description": {"content": [{"content": [{"text": description, "type": "text"}], "type": "paragraph"}]}
                    if description
                    else None,
                }
            }
            # Remove None description
            if payload["fields"]["description"] is None:
                del payload["fields"]["description"]

            response = requests.post(url, headers=headers, json=payload, timeout=10)
            response.raise_for_status()

            data = response.json()
            return {"success": True, "key": data.get("key"), "id": data.get("id")}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp_server.tool
    def get_jira_issue_details(issue_key: str) -> dict:
        """
        Get detailed information about a Jira issue.

        Retrieve full details of an issue including description, attachments, comments,
        history, and custom fields.

        Args:
            issue_key: The issue key (e.g., "PROJ-123")

        Returns:
            dict: Contains issue details including fields, assignee, reporter, history,
                 or 'error'
        """
        try:
            config = utils.get_atlassian_config()
            headers = utils.get_atlassian_auth_header()
            url = f"{config['site_url']}/rest/api/3/issues/{issue_key}"

            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()

            issue = response.json()
            fields = issue.get("fields", {})
            return {
                "success": True,
                "key": issue.get("key"),
                "summary": fields.get("summary"),
                "description": fields.get("description"),
                "status": fields.get("status", {}).get("name"),
                "assignee": fields.get("assignee", {}).get("displayName"),
                "reporter": fields.get("reporter", {}).get("displayName"),
                "type": fields.get("issuetype", {}).get("name"),
                "priority": fields.get("priority", {}).get("name"),
                "created": fields.get("created"),
                "updated": fields.get("updated"),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ========================================================================
    # Atlassian Confluence Tools
    # ========================================================================

    @mcp_server.tool
    def search_confluence(query: str, max_results: int = 20) -> dict:
        """
        Search for Confluence pages and spaces.

        Search across all Confluence content using text search. Useful for finding
        documentation, wikis, and team information.

        Args:
            query: Search query string (e.g., "API documentation")
            max_results: Maximum number of results to return (default: 20)

        Returns:
            dict: Contains 'results' list with page titles and spaces or 'error'
        """
        try:
            config = utils.get_atlassian_config()
            headers = utils.get_atlassian_auth_header()
            url = f"{config['site_url']}/rest/api/2/search"

            response = requests.get(
                url,
                headers=headers,
                params={"text": query, "limit": min(max_results, 50)},
                timeout=10,
            )
            response.raise_for_status()

            data = response.json()
            results = []
            for item in data.get("results", []):
                results.append(
                    {
                        "type": item.get("content", {}).get("type"),
                        "title": item.get("content", {}).get("title"),
                        "url": item.get("url"),
                        "space": item.get("space", {}).get("name"),
                    }
                )

            return {"success": True, "results": results, "total": data.get("size")}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp_server.tool
    def list_confluence_spaces() -> dict:
        """
        List all Confluence spaces you have access to.

        Get a list of all spaces in your Confluence instance that you can read.
        Useful for understanding your documentation structure.

        Returns:
            dict: Contains 'spaces' list with space names and keys or 'error'
        """
        try:
            config = utils.get_atlassian_config()
            headers = utils.get_atlassian_auth_header()
            url = f"{config['site_url']}/rest/api/2/spaces"

            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()

            data = response.json()
            spaces = []
            for space in data.get("space", []):
                spaces.append(
                    {
                        "key": space.get("key"),
                        "name": space.get("name"),
                        "type": space.get("type"),
                    }
                )

            return {"success": True, "spaces": spaces}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp_server.tool
    def create_confluence_page(
        space_key: str, title: str, body: str, parent_page_id: str = None
    ) -> dict:
        """
        Create a new Confluence page.

        Create a new wiki page in a space. Useful for documenting features,
        procedures, and team information.

        Args:
            space_key: The space key where the page will be created (e.g., "DOC")
            title: Title of the new page
            body: Page body content (supports basic markup/text)
            parent_page_id: Optional parent page ID for hierarchical organization

        Returns:
            dict: Contains 'id' and 'url' of created page or 'error'
        """
        try:
            config = utils.get_atlassian_config()
            headers = utils.get_atlassian_auth_header()
            url = f"{config['site_url']}/rest/api/2/pages"

            payload = {
                "spaceKey": space_key,
                "title": title,
                "body": body,
            }
            if parent_page_id:
                payload["parentPageId"] = parent_page_id

            response = requests.post(url, headers=headers, json=payload, timeout=10)
            response.raise_for_status()

            data = response.json()
            return {
                "success": True,
                "id": data.get("id"),
                "url": data.get("_links", {}).get("webui"),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp_server.tool
    def get_confluence_page_details(page_id: str) -> dict:
        """
        Get detailed information about a Confluence page.

        Retrieve full page content, metadata, version history, and more.

        Args:
            page_id: The page ID

        Returns:
            dict: Contains page title, content, space, version, created/updated dates
                 or 'error'
        """
        try:
            config = utils.get_atlassian_config()
            headers = utils.get_atlassian_auth_header()
            url = f"{config['site_url']}/rest/api/2/pages/{page_id}"

            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()

            page = response.json()
            return {
                "success": True,
                "id": page.get("id"),
                "title": page.get("title"),
                "space": page.get("space", {}).get("name"),
                "body": page.get("body"),
                "version": page.get("version", {}).get("number"),
                "created": page.get("createdDate"),
                "updated": page.get("lastUpdated"),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

