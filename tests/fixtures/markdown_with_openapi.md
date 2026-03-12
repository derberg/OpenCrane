# GitLab API Reference

This document describes the GitLab REST API endpoints.

### https://raw.githubusercontent.com/bump-sh/examples/refs/heads/main/apis/gitlab-openapi-source.yaml

```yaml
openapi: 3.0.1
info:
  title: GitLab API
  version: v4
  description: |
    An OpenAPI definition for the GitLab REST API.
    Few API resources or endpoints are currently included.
    The intent is to expand this to match the entire Markdown documentation of the API:
    <https://docs.gitlab.com/ee/api/>.
    Contributions are welcome.

    When viewing this on gitlab.com, you can test API calls directly from the browser
    against the `gitlab.com` instance, if you are logged in.
    The feature uses the current [GitLab session cookie](https://docs.gitlab.com/ee/api/#session-cookie),
    so each request is made using your account.

    Instructions for using this tool can be found in [Interactive API Documentation](https://docs.gitlab.com/ee/api/openapi/openapi_interactive.html)
  
  termsOfService: 'https://about.gitlab.com/terms/'
  license:
    name: CC BY-SA 4.0
    url: 'https://gitlab.com/gitlab-org/gitlab/-/blob/master/LICENSE'

servers:
  - url: https://www.gitlab.com/api/v4

security:
  - ApiKeyAuth: []

tags:
  - name: access_requests
    description: Operations related to access requests
  - name: badges
    description: Operations about badges
  - name: branches
    description: Operations about branches
  - name: jobs
    description: Operations related to CI Jobs
  - name: projects
    description: Operations related to projects

paths:
  /groups/{id}/access_requests:
    get:
      tags:
        - access_requests
      summary: Gets a list of access requests for a group.
      description: This feature was introduced in GitLab 8.11.
      operationId: getApiV4GroupsIdAccessRequests
      parameters:
        - name: id
          in: path
          description: The ID or URL-encoded path of the group owned by the authenticated user
          required: true
          schema:
            type: string
        - name: page
          in: query
          description: Current page number
          schema:
            type: integer
            format: int32
            default: 1
        - name: per_page
          in: query
          description: Number of items per page
          schema:
            type: integer
            format: int32
            default: 20
      responses:
        200:
          description: Gets a list of access requests for a group.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/API_Entities_AccessRequester'
    post:
      tags:
        - access_requests
      summary: Requests access for the authenticated user to a group.
      description: This feature was introduced in GitLab 8.11.
      operationId: postApiV4GroupsIdAccessRequests
      parameters:
        - name: id
          in: path
          description: The ID or URL-encoded path of the group owned by the authenticated user
          required: true
          schema:
            type: string
      responses:
        200:
          description: successful operation
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/API_Entities_AccessRequester'

  /groups/{id}/badges/{badge_id}:
    get:
      tags:
        - badges
      summary: Gets a badge of a group.
      description: This feature was introduced in GitLab 10.6.
      operationId: getApiV4GroupsIdBadgesBadgeId
      parameters:
        - name: id
          in: path
          description: The ID or URL-encoded path of the group owned by the authenticated user.
          required: true
          schema:
            type: string
        - name: badge_id
          in: path
          description: The badge ID
          required: true
          schema:
            type: integer
            format: int32
      responses:
        200:
          description: Gets a badge of a group.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/API_Entities_Badge'
    put:
      tags:
        - badges
      summary: Updates a badge of a group.
      description: This feature was introduced in GitLab 10.6.
      operationId: putApiV4GroupsIdBadgesBadgeId
      parameters:
        - name: id
          in: path
          description: The ID or URL-encoded path of the group owned by the authenticated user.
          required: true
          schema:
            type: string
        - name: badge_id
          in: path
          required: true
          schema:
            type: integer
            format: int32
      requestBody:
        content:
          application/json:
            schema:
              properties:
                link_url:
                  type: string
                  description: URL of the badge link
                image_url:
                  type: string
                  description: URL of the badge image
                name:
                  type: string
                  description: Name for the badge
      responses:
        200:
          description: Updates a badge of a group.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/API_Entities_Badge'

  /projects/{id}/repository/branches:
    get:
      tags:
        - branches
      description: Get a project repository branches
      operationId: getApiV4ProjectsIdRepositoryBranches
      parameters:
        - name: id
          in: path
          description: The ID or URL-encoded path of the project
          required: true
          schema:
            type: string
        - name: page
          in: query
          description: Current page number
          schema:
            type: integer
            format: int32
            default: 1
        - name: per_page
          in: query
          description: Number of items per page
          schema:
            type: integer
            format: int32
            default: 20
        - name: search
          in: query
          description: Return list of branches matching the search criteria
          schema:
            type: string
      responses:
        200:
          description: Get a project repository branches
          content:
            application/json:
              schema:
                type: array
                items:
                  $ref: '#/components/schemas/API_Entities_Branch'
        404:
          description: 404 Project Not Found
          content: {}
    post:
      tags:
        - branches
      description: Create branch
      operationId: postApiV4ProjectsIdRepositoryBranches
      parameters:
        - name: id
          in: path
          description: The ID or URL-encoded path of the project
          required: true
          schema:
            type: string
        - name: branch
          in: query
          description: The name of the branch
          required: true
          schema:
            type: string
        - name: ref
          in: query
          description: Create branch from commit sha or existing branch
          required: true
          schema:
            type: string
      responses:
        201:
          description: Create branch
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/API_Entities_Branch'
        400:
          description: Failed to create branch
          content: {}

  /projects/{id}/jobs:
    get:
      tags:
        - jobs
      summary: List jobs for a project
      operationId: listProjectJobs
      parameters:
        - name: id
          in: path
          required: true
          description: The ID of the project
          schema:
            type: integer
        - name: scope
          in: query
          required: false
          description: Return all jobs with the specified statuses
          schema:
            type: array
            items:
              type: string
      responses:
        '200':
          description: An array of jobs
          content:
            application/json:
              schema:
                type: array
                items:
                  $ref: '#/components/schemas/API_Entities_Job'

  /projects/{id}/jobs/{job_id}:
    get:
      tags:
        - jobs
      summary: Get a single job by ID
      operationId: getSingleJob
      parameters:
        - name: id
          in: path
          required: true
          description: The ID of the project
          schema:
            type: integer
        - name: job_id
          in: path
          required: true
          description: The ID of the job
          schema:
            type: integer
      responses:
        '200':
          description: A single job object
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/API_Entities_Job'

components:
  securitySchemes:
    ApiKeyAuth:
      type: apiKey
      in: header
      name: Private-Token

  schemas:
    API_Entities_AccessRequester:
      type: object
      properties:
        id:
          type: integer
          format: int32
          example: 1
        username:
          type: string
          example: admin
        name:
          type: string
          example: Administrator
        state:
          type: string
          example: active
        avatar_url:
          type: string
          example: https://gravatar.com/avatar/1
        web_url:
          type: string
          example: https://gitlab.example.com/root
        email:
          type: string
        requested_at:
          type: string
      description: API_Entities_AccessRequester model

    API_Entities_Badge:
      type: object
      properties:
        name:
          type: string
        link_url:
          type: string
        image_url:
          type: string
        rendered_link_url:
          type: string
        rendered_image_url:
          type: string
        id:
          type: string
        kind:
          type: string
      description: API_Entities_Badge model

    API_Entities_Branch:
      type: object
      properties:
        name:
          type: string
          example: master
        commit:
          $ref: '#/components/schemas/API_Entities_Commit'
        merged:
          type: boolean
          example: true
        protected:
          type: boolean
          example: true
        developers_can_push:
          type: boolean
          example: true
        developers_can_merge:
          type: boolean
          example: true
        can_push:
          type: boolean
          example: true
        default:
          type: boolean
          example: true
        web_url:
          type: string
          example: https://gitlab.example.com/Commit921/the-dude/-/tree/master
      description: API_Entities_Branch model

    API_Entities_Commit:
      type: object
      properties:
        id:
          type: string
          example: 2695effb5807a22ff3d138d593fd856244e155e7
        short_id:
          type: string
          example: 2695effb
        created_at:
          type: string
          format: date-time
          example: 2017-07-26T11:08:53+02:00
        title:
          type: string
          example: Initial commit
        message:
          type: string
          example: Initial commit
        author_name:
          type: string
          example: John Smith
        author_email:
          type: string
          example: john@example.com
        web_url:
          type: string
          example: https://gitlab.example.com/janedoe/gitlab-foss/-/commit/ed899a2f4b50b4370feeea94676502b42383c746

    API_Entities_Job:
      type: object
      properties:
        id:
          type: integer
          description: The ID of the job
        name:
          type: string
          description: The name of the job
        status:
          type: string
          description: The current status of the job
        stage:
          type: string
          description: The stage of the job in the CI/CD pipeline
        created_at:
          type: string
          format: date-time
          example: 2016-01-11T10:13:33.506Z
          description: The creation time of the job
        started_at:
          type: string
          format: date-time
          example: 2016-01-11T10:13:33.506Z
          description: The start time of the job
        finished_at:
          type: string
          format: date-time
          example: 2016-01-11T10:13:33.506Z
          description: The finish time of the job
        commit:
          $ref: '#/components/schemas/API_Entities_Commit'
        ref:
          type: string
          description: The reference for the job
        web_url:
          type: string
          description: The URL for accessing the job in the web interface
      description: API_Entities_Job model
```
