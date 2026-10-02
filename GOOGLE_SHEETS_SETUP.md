# Google Sheets Integration Setup Guide

## Prerequisites

1. Install required Python packages:
```bash
pip install requests
```

2. **Make your Google Sheet publicly accessible:**
   - Open your Google Sheet
   - Click "Share" button
   - Click "Change to anyone with the link"
   - Set permission to "Viewer"
   - Copy the link

**That's it! No OAuth, no tokens, no complex setup needed.**

## How It Works

The integration uses Google Sheets' public CSV export feature. Simply:
1. Make your sheet public (or share with "Anyone with the link")
2. Connect it using the sheet URL
3. Map the columns to lead fields
4. Data is automatically synced and displayed

## API Endpoints

### Step 1: Get Available Campaigns (Optional)
```
GET /google-sheets/available-campaigns
```
Returns: List of active campaigns to select from

### Step 2: Create Connection
```
POST /google-sheets/connect
{
  "connection_name": "Google Ads Lead Sheet",
  "sheet_url": "https://docs.google.com/spreadsheets/d/YOUR_SHEET_ID/edit",
  "sheet_name": "Sheet1",
  "sync_frequency": "Every 15 minutes",
  "status": "Active",
  "campaign_id": 1,
  "source": "Google Ads"
}
```
Returns: `connection_id`

**Note:** 
- `campaign_id` (optional) - Select a campaign from available campaigns. All imported leads will be assigned to this campaign.
- `source` (optional) - Source name for imported leads. This will be added to lead tags.

### Step 3: Get Available Columns and Fields
```
GET /google-sheets/connections/{connection_id}/columns
```
Returns: List of available columns in the Google Sheet

```
GET /google-sheets/available-lead-fields
```
Returns: List of all available lead fields that can be mapped

### Step 4: Set Field Mapping
```
POST /google-sheets/update-field-mapping/{connection_id}
[
  {"lead_field": "name", "sheet_column": "Column A", "required": false},
  {"lead_field": "email", "sheet_column": "Column B", "required": true},
  {"lead_field": "phone", "sheet_column": "Column C", "required": true},
  {"lead_field": "company", "sheet_column": "Column D", "required": false},
  {"lead_field": "sheets_lead_id", "sheet_column": "Column E", "required": false},
  {"lead_field": "ad_name", "sheet_column": "Column F", "required": false},
  {"lead_field": "platform", "sheet_column": "Column G", "required": false},
  {"lead_field": "what_best_describes_your_role", "sheet_column": "Column H", "required": false},
  {"lead_field": "what_would_you_most_like_to_improve_right_now", "sheet_column": "Column I", "required": false},
  {"lead_field": "when_are_you_planning_to_upgrade_or_adopt_clinic_software", "sheet_column": "Column J", "required": false},
  {"lead_field": "city", "sheet_column": "Column K", "required": false}
]
```

### Step 5: Preview Data (with mapped fields)
```
GET /google-sheets/preview/{connection_id}?limit=10
```
Returns: Preview of sheet data with mapped fields (without importing)

### Step 6: Sync Data (import leads)
```
POST /google-sheets/manual-sync/{connection_id}
```
This imports leads from the sheet based on field mapping.

### Get All Connections
```
GET /google-sheets/connections
```

### Update Field Mapping
```
POST /google-sheets/connections/{connection_id}/field-mapping
[
  {
    "lead_field": "name",
    "sheet_column": "Column A",
    "required": false
  },
  {
    "lead_field": "email",
    "sheet_column": "Column B",
    "required": true
  },
  {
    "lead_field": "phone",
    "sheet_column": "Column C",
    "required": true
  }
]
```

### Manual Sync
```
POST /google-sheets/connections/{connection_id}/sync
```

### Get Statistics
```
GET /google-sheets/stats
```

### Get Sync Logs
```
GET /google-sheets/sync-logs?connection_id=1&status=Success
```

## Sync Frequencies

- "Every 15 minutes"
- "Every 30 minutes"
- "Hourly"
- "Daily"

## Field Mapping

Map Google Sheet columns to Lead fields. Available fields:

### Basic Fields:
- `name` - Lead name
- `email` - Lead email (required for import)
- `phone` - Lead phone (required for import)
- `priority` - Lead priority (Low, Medium, High)
- `score` - Lead score (0-100)
- `source` - Lead source (if not mapped, will use connection's source value)
- `company` - Company name

### Google Sheets Integration Fields:
- `sheets_lead_id` - Lead ID from Google Sheets
- `ad_name` - Ad name
- `platform` - Platform name (e.g., Google Ads, Facebook Ads)
- `what_best_describes_your_role` - Role description
- `what_would_you_most_like_to_improve_right_now` - Improvement preference
- `when_are_you_planning_to_upgrade_or_adopt_clinic_software` - Upgrade timeline
- `city` - City name
- `lead_date` - Lead date/time (datetime field, supports formats: YYYY-MM-DD, MM/DD/YYYY, DD/MM/YYYY)

### Automatically Set Fields (Cannot be mapped):
These fields are automatically set from connection settings:
- `campaign_id` - Set from connection's `campaign_id`
- `status` - Always set to "New" for imported leads

**Note:** If `source` is not mapped from the sheet, it will automatically use the connection's `source` value.

### Sheet Column Format:
Sheet columns can be specified as:
- **"Column A"**, **"Column B"**, etc. (by column letter)
- **Direct header name** (if headers match exactly)

### Example Field Mapping:
```json
[
  {"lead_field": "name", "sheet_column": "Column A", "required": false},
  {"lead_field": "email", "sheet_column": "Column B", "required": true},
  {"lead_field": "phone", "sheet_column": "Column C", "required": true},
  {"lead_field": "sheets_lead_id", "sheet_column": "Column D", "required": false},
  {"lead_field": "ad_name", "sheet_column": "Column E", "required": false},
  {"lead_field": "platform", "sheet_column": "Column F", "required": false},
  {"lead_field": "what_best_describes_your_role", "sheet_column": "Column G", "required": false},
  {"lead_field": "what_would_you_most_like_to_improve_right_now", "sheet_column": "Column H", "required": false},
  {"lead_field": "when_are_you_planning_to_upgrade_or_adopt_clinic_software", "sheet_column": "Column I", "required": false},
  {"lead_field": "city", "sheet_column": "Column J", "required": false},
  {"lead_field": "lead_date", "sheet_column": "Column K", "required": false},
  {"lead_field": "source", "sheet_column": "Column L", "required": false},
  {"lead_field": "company", "sheet_column": "Column M", "required": false}
]
```

