# Lead File Import API Documentation

This document describes the API endpoints for importing leads from CSV, Excel, JSON, or TSV files.

## Prerequisites

1. Install required packages:
```bash
pip install pandas openpyxl
```

2. Run the SQL migration to create the `lead_imports` table:
```sql
-- Run create_lead_imports_table.sql
```

## API Endpoints

### 1. Upload File
**POST** `/leads/import/upload`

Upload a file (CSV, Excel, JSON, or TSV) and get a preview.

**Request:**
- Content-Type: `multipart/form-data`
- Body: File upload (max 10MB)

**Response:**
```json
{
  "file_id": 1,
  "filename": "leads.csv",
  "file_type": "CSV",
  "total_rows": 150,
  "sample_data": [
    {
      "name": "John Doe",
      "email": "john@example.com",
      "phone": "+1234567890"
    }
  ],
  "available_columns": ["name", "email", "phone", "company"],
  "available_lead_fields": ["name", "email", "phone", "company", ...]
}
```

### 2. Get Available Fields
**GET** `/leads/import/available-fields`

Get list of available lead fields that can be mapped.

**Response:**
```json
{
  "available_lead_fields": ["name", "email", "phone", ...],
  "required_fields": ["name", "email", "phone"],
  "optional_fields": ["company", "value", "score", ...]
}
```

### 3. Import Leads
**POST** `/leads/import/import`

Map fields and import leads from uploaded file.

**Request Body:**
```json
{
  "file_id": 1,
  "field_mapping": {
    "Full Name": "name",
    "Email Address": "email",
    "Phone Number": "phone",
    "Company Name": "company",
    "City": "city",
    "Source": "source"
  },
  "campaign_id": 5,
  "source": "File Upload",
  "status": "New",
  "priority": "Medium"
}
```

**Response:**
```json
{
  "id": 1,
  "filename": "leads.csv",
  "file_type": "CSV",
  "total_records": 150,
  "imported_records": 148,
  "failed_records": 2,
  "status": "Completed",
  "field_mapping": {...},
  "error_details": "Row 5: Invalid email format...",
  "imported_by": "admin",
  "created_at": "2024-01-15T10:00:00",
  "updated_at": "2024-01-15T10:05:00"
}
```

### 4. Get Import History
**GET** `/leads/import/history?skip=0&limit=20`

Get list of all imports.

**Query Parameters:**
- `skip`: Number of records to skip (default: 0)
- `limit`: Maximum number of records to return (default: 20, max: 100)

**Response:**
```json
[
  {
    "id": 1,
    "filename": "leads.csv",
    "file_type": "CSV",
    "total_records": 150,
    "imported_records": 148,
    "failed_records": 2,
    "status": "Completed",
    "imported_by": "admin",
    "created_at": "2024-01-15T10:00:00"
  }
]
```

### 5. Get Import Details
**GET** `/leads/import/history/{import_id}`

Get detailed information about a specific import.

**Response:**
```json
{
  "id": 1,
  "filename": "leads.csv",
  "file_type": "CSV",
  "total_records": 150,
  "imported_records": 148,
  "failed_records": 2,
  "status": "Completed",
  "field_mapping": {...},
  "error_details": "Row 5: Invalid email format...",
  "imported_by": "admin",
  "created_at": "2024-01-15T10:00:00",
  "updated_at": "2024-01-15T10:05:00"
}
```

### 6. Get Import Statistics
**GET** `/leads/import/stats`

Get overall import statistics.

**Response:**
```json
{
  "total_imports": 3,
  "total_records": 467,
  "failed_records": 6,
  "success_rate": 98.71
}
```

### 7. Download CSV Template
**GET** `/leads/import/template/csv`

Download a CSV template file with sample data.

### 8. Download Excel Template
**GET** `/leads/import/template/excel`

Download an Excel template file with sample data.

## Field Mapping

### Available Lead Fields

**Required Fields:**
- `name` - Lead name
- `email` - Email address (must be unique)
- `phone` - Phone number

**Optional Fields:**
- `company` - Company name
- `value` - Lead value (numeric)
- `score` - Lead score (0-100)
- `status` - Lead status (default: "New")
- `priority` - Lead priority (High, Medium, Low)
- `tags` - Comma-separated tags
- `sheets_lead_id` - Google Sheets lead ID
- `ad_name` - Ad name
- `platform` - Platform name
- `what_best_describes_your_role` - Role description
- `what_would_you_most_like_to_improve_right_now` - Improvement area
- `when_are_you_planning_to_upgrade_or_adopt_clinic_software` - Upgrade timeline
- `city` - City name
- `lead_date` - Lead date (datetime)
- `source` - Lead source

### Date Formats Supported

The `lead_date` field supports multiple date formats:
- `YYYY-MM-DD HH:MM:SS`
- `YYYY-MM-DD`
- `DD/MM/YYYY HH:MM:SS`
- `DD/MM/YYYY`
- `MM/DD/YYYY HH:MM:SS`
- `MM/DD/YYYY`
- `DD-MM-YYYY HH:MM:SS`
- `DD-MM-YYYY`
- `YYYY/MM/DD HH:MM:SS`
- `YYYY/MM/DD`

## Import Behavior

1. **Duplicate Handling**: If a lead with the same email already exists, the system will update the existing lead with new data (except name, email, and phone).

2. **Validation**: 
   - Required fields (name, email, phone) must be present
   - Email format is validated
   - Score is clamped between 0-100
   - Value is converted to float

3. **Error Handling**: Failed rows are tracked with error messages, but the import continues for other rows.

4. **Status Flow**: 
   - `Pending` → File uploaded, waiting for mapping
   - `Processing` → Import in progress
   - `Completed` → Import finished
   - `Failed` → Import failed (usually due to file parsing errors)

## Example Workflow

1. **Upload File**: `POST /leads/import/upload`
   - Upload your CSV/Excel file
   - Get `file_id` and preview

2. **Map Fields**: `POST /leads/import/import`
   - Provide `file_id` and `field_mapping`
   - System imports leads

3. **Check Results**: `GET /leads/import/history/{import_id}`
   - View import details and any errors

## Notes

- Maximum file size: 10MB
- Supported formats: CSV, Excel (.xlsx, .xls), JSON, TSV
- All endpoints require authentication
- **Files are NOT stored on the server** - only parsed data is stored in the database as JSON
- Files are processed entirely in memory for security and efficiency

