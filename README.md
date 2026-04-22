# AI-3D-Hub

AI-3D-Hub is a lightweight, self-hosted Digital Asset Management (DAM) tool designed specifically for managing 3D printing files (STL, 3MF, F3D, images, etc.). It provides an efficient, local alternative to heavier tools, focusing on speed, local data storage, and integrated AI support.

## Features

- **Fast Local Storage**: Your files are stored locally, avoiding reliance on external cloud storage. Files are automatically organized into project-specific directories.
- **AI Integration**: Built-in integration with Anthropic's Claude to automatically generate SEO-optimized titles and descriptions for your models (ideal for platforms like Makerworld).
- **Lightweight Architecture**: Built with a fast Python backend (FastAPI, SQLAlchemy, SQLite) and a clean, responsive frontend (Vanilla HTML5/JS, Tailwind CSS) without the overhead of heavy frameworks.
- **Easy Deployment**: Fully containerized with Docker and Docker Compose for hassle-free installation.

## Prerequisites

- **Docker** and **Docker Compose** (Recommended)
- **Python 3.11+** (If running locally without Docker)
- An **Anthropic API Key** (Optional, required only for the AI text generation feature)

## Installation Guide

### Option 1: Using Docker Compose (Recommended)

1. **Clone the repository:**
   ```bash
   git clone https://github.com/Drondernei/ai3dhub.git
   cd ai3dhub
   ```

2. **Configure Environment Variables:**
   Copy the example environment file and add your Anthropic API key.
   ```bash
   cp .env.example .env
   # Edit .env and set your ANTHROPIC_API_KEY
   ```

3. **Start the application:**
   ```bash
   docker-compose up -d
   ```

4. **Access the Web Interface:**
   Open your browser and navigate to `http://localhost:8000`.

### Option 2: Running Locally (Python)

1. **Clone the repository:**
   ```bash
   git clone https://github.com/yourusername/ai3dhub.git
   cd ai3dhub
   ```

2. **Install Dependencies:**
   Ensure you have Python 3.11+ installed.
   ```bash
   pip install -r requirements.txt
   ```

3. **Set Environment Variables:**
   Set the `ANTHROPIC_API_KEY` environment variable.
   ```bash
   export ANTHROPIC_API_KEY=your_api_key_here
   ```

4. **Start the Application:**
   ```bash
   uvicorn main:app --host 0.0.0.0 --port 8000
   ```

5. **Access the Web Interface:**
   Open your browser and navigate to `http://localhost:8000`.

## Usage Guide

### Managing Projects
- Access the web interface to view, create, edit, or delete your 3D printing projects.
- Each project can include an internal title, public title, description, tags, materials, hardware, and an assigned cover image.

### Uploading Files
- You can upload multiple files (STL, 3MF, F3D, images) to a project.
- Files are initially staged in a temporary directory (`uploads/temp/`) and automatically moved to a sanitized, project-specific directory (`uploads/[Project_Name]/`) when the project is saved or updated.

### Using AI Generation
- When editing or creating a project, you can use the AI feature to generate compelling titles and descriptions.
- Provide context about the 3D model, such as the problem it solves, the target audience, and its features.
- The AI (powered by Anthropic's Claude) will generate a structured title and description that you can directly apply to your project.

### Data Storage location
- **Database:** All project metadata is stored in a local SQLite database at `data/ai3dhub.db`.
- **Files:** All uploaded 3D models and images are stored physically in the `uploads/` directory.

---
*Hub for all 3d Models you love to print so much. AI Integration available if needed.*
