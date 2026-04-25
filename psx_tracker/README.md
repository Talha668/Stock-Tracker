# PSX Tracker

A Django-based tracking and monitoring application with asynchronous task processing via Celery and Redis. Features automated data collection, scheduled updates, and a RESTful API interface.

## Features

- **Django Web Framework** — Robust backend with admin interface
- **Asynchronous Task Processing** — Celery workers for background jobs
- **Scheduled Jobs** — Periodic tasks via Celery Beat
- **Web Scraping** — Automated data collection using curl_cffi and BeautifulSoup
- **WebSocket Support** — Real-time updates via Django Channels
- **CORS Enabled** — Cross-origin resource sharing for frontend integration
- **PostgreSQL Database** — Production-ready relational database

## Tech Stack

- **Backend:** Django, Django REST Framework
- **Database:** PostgreSQL
- **Task Queue:** Celery + Redis
- **WebSocket:** Django Channels + Channels Redis
- **HTTP Client:** curl_cffi (impersonation support)
- **Parsing:** BeautifulSoup4
- **Environment:** python-decouple

## Prerequisites

- Python 3.11+
- PostgreSQL 14+
- Redis server (local or remote)
- Windows (for `.bat` scripts) or adapt for Linux/Mac

## Installation

**Clone the repository**
   ```bash
   git clone <repo-url>   (put repo url)
   cd psx_tracker
   create a virtaul environment
   pip install requirements.txt
   create postgresSQL database
   run migrations
   start redis
   start celery
   start development server