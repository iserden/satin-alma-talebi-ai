AI-Assisted Purchase Request Automation

AI-Assisted Purchase Request Automation is a Django-based web application developed to digitally process purchase request forms submitted by businesses, match the extracted items with the product catalog, consolidate approved requests, and transfer validated data to SAP Business One.

The project uses artificial intelligence to support document reading and product matching processes and communicates with SAP Business One through the Service Layer API.

Key Features

Uploading purchase request forms in PDF and image formats

Reading form data with the Gemini API

Automatically matching extracted products with the system product catalog

Displaying confidence scores for product matches

Allowing users to review and edit matches

Learning alternative product names from manual confirmations

Approving purchase requests

Consolidating multiple approved requests into a single purchase request

Automatically calculating weekly product quantities

Generating Excel, CSV, and JSON exports

Previewing purchase request data before SAP transfer

Creating real Purchase Requests in SAP Business One

Storing SAP DocEntry and DocNum values in the system

Preventing the same request from being submitted to SAP more than once

Portable development environment with Docker

Technologies Used

Backend

Python 3.12

Django 5.2

SQLite

Django ORM

Artificial Intelligence

Google Gemini API

Google GenAI Python SDK

RapidFuzz

SAP Integration

SAP Business One

SAP Business One Service Layer

REST / OData API

Python Requests

File Processing

Pillow

OpenPyXL

Deployment / Development

Docker

Docker Compose

Git

GitHub

System Workflow

Purchase Request Form
        ↓
Form Upload
        ↓
Document Analysis with Gemini
        ↓
Product Data Extraction
        ↓
Product Catalog Matching
        ↓
User Review
        ↓
Request Approval
        ↓
Consolidation of Multiple Requests
        ↓
SAP Preview
        ↓
SAP Business One Service Layer
        ↓
Purchase Request

Installation

This project is designed to run using Docker.

The following software is sufficient on the machine where the project will be run:

Git

Docker Desktop

There is no need to install Python or create a virtual environment separately.

1. Clone the Repository

Make sure you have access to the private GitHub repository.

git clone <repository-url>

Then navigate to the project directory:

cd satin-alma-talebi-ai

2. Create the Environment File

The project includes an example environment file:

.env.example

Create a copy of this file and rename it to:

.env

PowerShell:

Copy-Item .env.example .env

Linux/macOS:

cp .env.example .env

3. Configure .env

Fill in the required fields in the .env file.

Example:

DJANGO_SECRET_KEY=your-secret-key
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1

GEMINI_API_KEY=your-gemini-api-key
GEMINI_MODEL=your-gemini-model

SAP_BASE_URL=https://mersapvm01:50000/b1s/v1
SAP_COMPANY_DB=your-company-database
SAP_USERNAME=your-sap-username
SAP_PASSWORD=your-sap-password
SAP_VERIFY_SSL=false
SAP_TIMEOUT=30
SAP_DEFAULT_WAREHOUSE=your-warehouse-code

Real usernames, passwords, and API keys must not be stored in the repository.

Running with Docker

Docker Desktop must be running.

From the project directory, run:

docker compose up --build

The first run may take several minutes because Docker images and Python packages need to be downloaded.

After a successful startup, the terminal should display output similar to:

Starting development server at http://0.0.0.0:8001/

The application can then be opened at:

http://127.0.0.1:8001/

Database Migration

After the initial setup, run the migrations:

docker compose exec web python manage.py migrate

To check migration status:

docker compose exec web python manage.py showmigrations

Creating a Django Admin User

To create an admin user during the initial setup, run:

docker compose exec web python manage.py createsuperuser

The command will ask for:

Username
Email
Password

The admin panel is available at:

http://127.0.0.1:8001/admin/

SAP Business One Connection

The application communicates with SAP Business One through the Service Layer.

The SAP connection is configured using the following environment variables in .env:

SAP_BASE_URL=
SAP_COMPANY_DB=
SAP_USERNAME=
SAP_PASSWORD=
SAP_VERIFY_SSL=
SAP_TIMEOUT=
SAP_DEFAULT_WAREHOUSE=

If the Service Layer is accessed through a hostname in the current company environment, the required hostname mapping must be defined in Docker Compose.

Example:

extra_hosts:
  - "mersapvm01:<SAP-SERVER-IP>"

Because the SAP server address may vary between environments, the required IP address should be obtained from the system administrator.

Testing the SAP Connection

To test SAP login from inside the container:

docker compose exec web python test_sap_login.py

A successful connection should produce output similar to:

HTTP status code: 200
RESULT: SAP Service Layer login successful.

Gemini API Connection

The Gemini API key is read from .env:

GEMINI_API_KEY=

The API key must never be hard-coded directly into the source code.

Docker Commands

Start the application:

docker compose up

Rebuild the image:

docker compose up --build

Run in the background:

docker compose up -d

Stop the containers:

docker compose down

View running containers:

docker compose ps

View logs:

docker compose logs -f web

Run a Django command inside the container:

docker compose exec web python manage.py <command>

Project Structure

satin-alma-talebi-ai/
│
├── config/
│   ├── settings.py
│   ├── urls.py
│   ├── asgi.py
│   └── wsgi.py
│
├── requests_app/
│   ├── migrations/
│   ├── services/
│   ├── templates/
│   ├── admin.py
│   ├── forms.py
│   ├── models.py
│   ├── urls.py
│   └── views.py
│
├── static/
├── templates/
│
├── Dockerfile
├── compose.yaml
├── .dockerignore
├── .env.example
├── .gitignore
├── requirements.txt
├── test_sap_login.py
└── manage.py

Core Services

The main business logic of the application is located under requests_app/services/.

Key services include:

gemini_service.py

Handles form analysis through the Gemini API.

product_matching_service.py

Matches products extracted by AI with the product catalog.

alias_learning_service.py

Creates alternative product names from manually confirmed product matches.

approval_service.py

Manages purchase request approval processes.

consolidation_service.py

Consolidates multiple purchase requests.

consolidation_export_service.py

Generates Excel, CSV, and JSON exports.

sap_service_layer_client.py

Manages communication with SAP Business One Service Layer.

sap_purchase_request_builder.py

Builds the Purchase Request payload to be sent to SAP.

sap_purchase_request_service.py

Handles sending the Purchase Request to SAP Business One and storing the returned SAP document information.

Data Storage

SQLite is used in the development and demo environment.

db.sqlite3

This file is not committed to the Git repository.

Docker Compose mounts this file to the host machine as a volume so that existing data can persist even if the container is removed.

Uploaded documents are stored in:

media/

This directory is also excluded from the repository.

Pulling New Updates

If new changes have been added to the repository, run:

git pull origin main

Then rebuild the Docker image:

docker compose up --build

If there are new migrations, run:

docker compose exec web python manage.py migrate

Development Workflow

When developing a new feature, it is recommended to create a new branch instead of working directly on main.

Example:

git checkout -b feature/new-feature

After making changes:

git add .
git commit -m "Add: new feature"
git push -u origin feature/new-feature

A Pull Request can then be created on GitHub.

Security

The following files and information must never be committed to the Git repository:

.env
db.sqlite3
media/
.venv/

The following information must especially never be hard-coded directly into the source code:

Gemini API Key

SAP username and password

Django Secret Key

Production database credentials

Internal company access information

These values should be managed through environment variables.

Project Status

The current version is a working MVP / internal demo version.

Completed core functionality:

Form upload                         ✅
Gemini document analysis           ✅
Product catalog                    ✅
AI product matching                ✅
Manual review                      ✅
Request approval                   ✅
Request consolidation              ✅
Excel / CSV / JSON export          ✅
SAP Business One Service Layer     ✅
SAP Purchase Request creation      ✅
SAP DocEntry / DocNum storage      ✅
Duplicate submission protection    ✅
Docker                              ✅

Before production use, it is recommended to configure a production web server, centralized database, SSL, user authorization, logging, backup, and deployment infrastructure according to enterprise standards.

Repository Access

This repository is currently kept private.

Users who will work on the project should be added to the repository as collaborators or through the relevant organization/team.

Note

This project was developed for internal development, evaluation, and demo purposes. SAP Business One credentials, API keys, and company data must remain outside the repository.
