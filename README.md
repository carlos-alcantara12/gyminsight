# GymInsight

[English](README.md) · [Português](README.pt-BR.md)

A gym management application built with **Python, Django, and Django REST Framework**. It brings branch operations, memberships, attendance, and financial records into one system.

## Key features

- Branch, employee, member, and membership plan management.
- Enrollment periods, cancellations, expiration notices, and renewal rules.
- Attendance records with access validation by branch and contracted plan.
- Billing, outstanding balances, and manual payment recording by Pix or card.
- Attendance and financial reports, including revenue by branch.
- Role-based API permissions and audit records.
- A demonstration network with five branches and 50 fictional members.

Payments are recorded administratively; the application does not process card or bank transactions.

## Technology and architecture

The Django backend provides an API through Django REST Framework. Business services centralize enrollment, attendance, billing, cancellation, and renewal rules. SQLite is used for local development.

Main entities include branches, employees, members, plans, enrollments, attendance, payments, and audit logs. Existing model names and commands remain in Portuguese.

## Local setup

From the repository root, in PowerShell:

```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py configurar_grupos
python manage.py createsuperuser
python manage.py vincular_gerente --usuario YOUR_USERNAME --unidade "Unidade Central"
python manage.py runserver
```

Replace `YOUR_USERNAME` with the superuser account you created. Open [Django Admin](http://127.0.0.1:8000/admin/) or [API login](http://127.0.0.1:8000/api/auth/login/). Admin and API access require an active employee and branch association.

On Linux or macOS, use `python3 -m venv .venv` and `source .venv/bin/activate` for the environment setup.

## Demo data

In a **new, empty demonstration installation**, run the following after migrations and group setup:

```powershell
python manage.py criar_rede_demo
```

This creates five branches, 50 fictional members, and the Tradicional, Premium, and Diamante plans. Do not run demo setup against real operational data or replace an existing database with the demonstration database.

## Validation

```powershell
python manage.py check
python manage.py test core
```

## Operational notes

- The daily `python manage.py rotina_diaria` command handles expiration, status synchronization, eligible renewals, and missing billing records. Schedule it for ongoing operation.
- Existing installations should preserve their databases and apply migrations.
- Production deployment requires environment configuration, HTTPS, backups, and defined data protection procedures.

## Documentation

The [complete operational reference in Portuguese](README.pt-BR.md) preserves detailed API routes, permissions, billing rules, Windows scheduling, legacy reconciliation, and deployment instructions.

- [Backend documentation](backend/README.md)
- [Entity relationship model](DER.md)
- [Database modeling](MODELAGEM_BANCO.md)
- [Data protection notes](LGPD.md)
