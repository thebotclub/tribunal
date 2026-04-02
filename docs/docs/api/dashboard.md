# Dashboard API Reference

The Team Dashboard provides a REST API for centralized project governance data.

## Start the Server

```bash
tribunal-dashboard --port 8700 --data-dir /path/to/data
```

## Endpoints

### GET /api/health

Health check.

### GET /api/projects

List all tracked projects.

### GET /api/summary

Get aggregated summary across all projects.

### GET /api/projects/{id}/audit

Get audit entries for a project.

### GET /api/projects/{id}/cost

Get cost data for a project.

### GET /api/projects/{id}/agents

Get agent data for a project.

### POST /api/projects/{id}/report

Submit a governance report for a project.

**Body:** JSON with `project_name`, `cost`, `audit_entries`, `agents`.
