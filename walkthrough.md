# Walkthrough: Pharmacy Inventory Control Panel (RxStock)

The Pharmacy Inventory Management System (RxStock) has been successfully built and configured in Python/Django using a MySQL database backend. 

The application implements a premium, custom-tailored dark slate and glowing teal user interface styled with Tailwind CSS v3, and includes Alpine.js for modal/sidebar interactivity. It is pre-seeded with rich sample data and configured to run locally out-of-the-box.

---

## Technical Stack & Configuration
- **Backend Framework**: Python Django 6.0.6
- **Database Driver**: `PyMySQL` registered as the MySQL database adapter.
- **Database Name**: `pharmacy_inventory` (verified and auto-created on local MySQL host `127.0.0.1:3306` with user `root` and empty password).
- **Styling & Interactivity**: Tailwind CSS v3 Play CDN and Alpine.js.
- **Excel & Spreadsheet Parsing**: `openpyxl` v3.1.5 (installed and configured inside virtual environment).
- **Virtual Environment**: Configured and activated under `venv/`.

---

## Implemented Features

### 1. Bulk Drug Ingestion (Excel / CSV Upload) (New Module)
Pharmacy managers can import large drug lists simultaneously.
- **Format Compatibility**: Dynamically parses both Excel (`.xlsx`) and CSV (`.csv`) spreadsheets.
- **Template Download**: Provides an on-demand generated template containing correct system headers: `drug_name`, `category`, `unit`, `reorder_level`, `min_stock`, `max_stock`, `description` along with pre-filled mock records.
- **Case-Insensitive Choice Mapping**: Gracefully translates mismatched casings (e.g., mapping `SYRUP`, `syrup` to Title Case `Syrup` choice) for both categories and units.
- **Verification & Integrity**: Checks for required columns. All numeric limits are strictly validated (must be integers >= 0).
- **Atomic Operations**: Processes all rows in a single database transaction block (`transaction.atomic`). If any row contains errors, the entire import rolls back, preventing database pollution, and displays detailed line-by-line validation notifications (e.g. `Row 4: Invalid category 'Liquid'`).
- **Duplicate Skipping**: Existing drugs are automatically skipped without stopping the ingestion flow.

### 2. User Management & Role Authorization
Administrators can fully manage system users directly from the UI control panel.
- **User Directory**: View all system users, their full names, contact info, and roles.
- **Role Assignment**: Assign one of three access roles:
  - **`ADMIN` (Administrator)**: Full privileges across the entire catalog, transaction postings, and access to User Management.
  - **`PHARMACIST` (Pharmacist)**: Authorization to perform stock dispatches (Stock-Out), check alerts, view catalog details, and export reports.
  - **`STOREKEEPER` (Storekeeper)**: Authorization to record incoming stock deliveries (Stock-In) and manage batch details.
- **Password Security**: New passwords are securely hashed using PBKDF2 algorithms automatically. Password fields are optional during user profile edits (leave blank to retain current password).
- **Security Check**: Enforced by a custom `@admin_required` decorator. If non-admin roles try to visit `/users/` directly, they are redirected to the dashboard with an "Access Denied" notice. Self-deletion of the active logged-in administrator is securely blocked.

### 3. Dynamically Persistent Dark & Light Mode
Users can easily switch between themes using a beautiful Sun/Moon icon toggle switch in the top header.
- **Tailwind Class Dark Mode**: Styled with Tailwind's `class` dark mode strategy.
- **Alpine.js Interactivity**: State is managed via Alpine.js global reactive data binding on the body tag.
- **Zero-Flicker Persistence**: Uses `localStorage` to save the theme preference. A small, blocking scripts wrapper is injected into the HTML `<head>` tag to apply the `.dark` class before the body renders, preventing white/dark screen flashes.
- **Responsive Theme Tokens**: Forms, tables, cards, texts, buttons, and alert highlights fully adapt color-ways.

### 4. Automated Expiry & Reorder Alerts
Operates dynamically on database changes and triggers:
- **Expiry Warnings**: Color-coded based on days remaining:
  - **Critical Expiry** (0-30 days): Red alert badges.
  - **Planning Zone** (31-90 days): Yellow alert badges.
  - **Monitoring Zone** (91-180 days): Blue alert badges.
  - **Expired** (<= 0 days): Bold dark-red alert.
- **Reorder Alerts**: Triggers a notification and displays a suggested order quantity (calculated as `Max Stock - Current Stock`) when the total available units of a drug falls below the drug's reorder threshold.

### 5. FEFO-Driven Stock Transactions
- **Stock-In**: Ingests new batches with manufacturing/expiry dates and maps them to suppliers.
- **Stock-Out (FEFO)**: Implements **First-Expired, First-Out (FEFO)** algorithm by default to automatically deduct stock from the soonest-expiring active batches first, preventing pharmaceutical waste.
- **Stock-Out (Manual Batch)**: Allows pharmacists to manually select a specific batch code for custom dispatches.

### 6. Reports & Auditable Data Exports
- Displays monthly statistics, category breakdowns, and a 180-day upcoming expirations forecast.
- Custom CSV export utilities for the complete **Drug Inventory** list and **Transaction Auditing Log**.

---

## Credentials & Demo Accounts
The database is fully migrated and pre-seeded. You can log in using any of the following accounts:

| Username | Password | Role | Description |
| :--- | :--- | :--- | :--- |
| `admin` | `admin123` | Administrator | Full access to catalog, batches, and User Management. |
| `pharmacist` | `pharm123` | Pharmacist | Access to view logs, alerts, and perform stock dispatches. |
| `storekeeper` | `store123` | Storekeeper | Access to record incoming stock deliveries. |

---

## Verification & Updates

### 1. Template Error Resolutions
- **Batches Directory Syntax Error**: Resolved a `TemplateSyntaxError` at `/batches/` where the custom block tag `blockpage_title` was written as a single typo inside the `title` block in [list.html](file:///c:/Users/IT%20HOD/Documents/Lasuproject/invetory-management/inventory/templates/inventory/batches/list.html#L3).
- **Suppliers Creation Syntax Error**: Fixed a `TemplateSyntaxError` at `/suppliers/add/` caused by an unclosed `{% block content %}` tag in [form.html](file:///c:/Users/IT%20HOD/Documents/Lasuproject/invetory-management/inventory/templates/inventory/suppliers/form.html#L80-L83).

### 2. Time-Based Expiry Filtering & Exporting on Reports Dashboard
Added an interactive filter panel and export capability on the **Reports & System Analytics** page:
- **Preset Options**: View soon-to-expire drug batches across horizons of 30, 90, 180 (default), or 365 days, or view all future expirations.
- **Custom Date Range**: Use Alpine.js to dynamically toggle custom `Start Date` and `End Date` inputs for fine-grained auditing.
- **Interactive Badge Count**: Displays the precise number of expiring batches matching the current filter horizon.
- **Filtered CSV Export**: Allows users to download the exact filtered set of expiring batches directly to a CSV file (e.g. `expiring_batches_30_days.csv` or `expiring_batches_custom_2026-07-02_to_2026-08-02.csv`) with the click of an "Export CSV" button in the card header.

### 3. Automated Tests
We expanded the test suite in [tests.py](file:///c:/Users/IT%20HOD/Documents/Lasuproject/invetory-management/inventory/tests.py) to cover the new report dashboard filters and CSV exports.
All 11 unit tests run and pass successfully:
```bash
Creating test database for alias 'default'...
System check identified some issues:

WARNINGS:
?: (staticfiles.W004) The directory 'C:\Users\IT HOD\Documents\Lasuproject\invetory-management\static' in the STATICFILES_DIRS setting does not exist.

System check identified 1 issue (0 silenced).
...........
----------------------------------------------------------------------
Ran 11 tests in 18.429s

OK
Destroying test database for alias 'default'...
Found 11 test(s).
```


---

## How to Run the Application

To launch the development server, run the following commands in your terminal:

1. **Activate Virtual Environment**:
   ```powershell
   .\venv\Scripts\activate
   ```
2. **Launch Server**:
   ```bash
   python manage.py runserver
   ```
3. **Open browser**: Go to [http://127.0.0.1:8000/](http://127.0.0.1:8000/) and log in with one of the seeded accounts above!

