# Walkthrough: Pharmacy Inventory Control Panel (RxStock)

The Pharmacy Inventory Management System (RxStock) has been successfully built and configured in Python/Django using a MySQL database backend. 

The application implements a premium, custom-tailored dark slate and glowing teal user interface styled with Tailwind CSS v3, and includes Alpine.js for modal/sidebar interactivity. It is pre-seeded with rich sample data and configured to run locally out-of-the-box.

---

## Technical Stack & Configuration
- **Backend Framework**: Python Django 6.0.6
- **Database Driver**: `PyMySQL` registered as the MySQL database adapter.
- **Database Name**: `pharmacy_inventory` (verified and auto-created on local MySQL host `127.0.0.1:3306` with user `root` and empty password).
- **Styling & Interactivity**: Tailwind CSS v3 Play CDN and Alpine.js.
- **Virtual Environment**: Configured and activated under `venv/`.

---

## Implemented Features

### 1. User Management & Role Authorization
Administrators can fully manage system users directly from the UI control panel.
- **User Directory**: View all system users, their full names, contact info, and roles.
- **Role Assignment**: Assign one of three access roles:
  - **`ADMIN` (Administrator)**: Full privileges across the entire catalog, transaction postings, and access to User Management.
  - **`PHARMACIST` (Pharmacist)**: Authorization to perform stock dispatches (Stock-Out), check alerts, view catalog details, and export reports.
  - **`STOREKEEPER` (Storekeeper)**: Authorization to record incoming stock deliveries (Stock-In) and manage batch details.
- **Password Security**: New passwords are securely hashed using PBKDF2 algorithms automatically. Password fields are optional during user profile edits (leave blank to retain current password).
- **Security Check**: Enforced by a custom `@admin_required` decorator. If non-admin roles try to visit `/users/` directly, they are redirected to the dashboard with an "Access Denied" notice. Self-deletion of the active logged-in administrator is securely blocked.

### 2. Dynamically Persistent Dark & Light Mode
Users can easily switch between themes using a beautiful Sun/Moon icon toggle switch in the top header.
- **Tailwind Class Dark Mode**: Styled with Tailwind's `class` dark mode strategy.
- **Alpine.js Interactivity**: State is managed via Alpine.js global reactive data binding on the body tag.
- **Zero-Flicker Persistence**: Uses `localStorage` to save the theme preference. A small, blocking scripts wrapper is injected into the HTML `<head>` tag to apply the `.dark` class before the body renders, preventing white/dark screen flashes.
- **Responsive Theme Tokens**: Forms, tables, cards, texts, buttons, and alert highlights fully adapt color-ways:
  - **Dark Mode**: Slate-900 / Slate-950 layouts with teal/emerald accents.
  - **Light Mode**: White / Slate-50 layouts with soft grey borders and clean teal highlights.

### 3. Automated Expiry & Reorder Alerts
Operates dynamically on database changes and triggers:
- **Expiry Warnings**: Color-coded based on days remaining:
  - **Critical Expiry** (0-30 days): Red alert badges.
  - **Planning Zone** (31-90 days): Yellow alert badges.
  - **Monitoring Zone** (91-180 days): Blue alert badges.
  - **Expired** (<= 0 days): Bold dark-red alert.
- **Reorder Alerts**: Triggers a notification and displays a suggested order quantity (calculated as `Max Stock - Current Stock`) when the total available units of a drug falls below the drug's reorder threshold.

### 4. FEFO-Driven Stock Transactions
- **Stock-In**: Ingests new batches with manufacturing/expiry dates and maps them to suppliers.
- **Stock-Out (FEFO)**: Implements **First-Expired, First-Out (FEFO)** algorithm by default to automatically deduct stock from the soonest-expiring active batches first, preventing pharmaceutical waste.
- **Stock-Out (Manual Batch)**: Allows pharmacists to manually select a specific batch code for custom dispatches.

### 5. Reports & Auditable Data Exports
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

## Verification Results

### Automated Tests
We wrote a test suite in [tests.py](file:///c:/Users/IT%20DEPT/Downloads/mr_lary_project/inventory/tests.py) verifying the core domain logic:
1. Expiry status zone classification.
2. Low stock reorder properties.
3. FEFO distribution logic (verifying multi-batch deductions).
4. Auto-alert generation and resolution.
5. Role-based access security checking (ensuring non-admins cannot access User Management).

All 6 unit tests passed successfully:
```bash
Creating test database for alias 'default'...
......
----------------------------------------------------------------------
Ran 6 tests in 13.787s

OK
Destroying test database for alias 'default'...
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
