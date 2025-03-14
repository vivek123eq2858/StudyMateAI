StudyMate AI

Project Description
This project is a Flask-based web application designed to help users extract text from uploaded documents (PDFs or images) and interactively ask questions about the content. It leverages the Gemini API for text extraction and question answering, and includes features like user authentication, email verification, and a logging system for error tracking. Users can toggle between strict mode (answers derived only from the uploaded document) and non-strict mode (answers from the Gemini API's general knowledge). The application also supports bulk question answering for multiple queries at once.

Technology Stack
Backend
Python: Primary programming language.

Flask: Web framework for building the application.

SQLite: Lightweight database for storing user information.

Google Gemini API: For text extraction and question answering.

ZeroBounce API: For email verification during user signup.

Poppler: For converting PDFs to images.

Pillow (PIL): For image processing.

ThreadPoolExecutor: For parallel processing of document pages.

Frontend
HTML/CSS: For building the user interface.

JavaScript: For interactive features and API calls.
