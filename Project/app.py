from flask import Flask, render_template, request, jsonify, session, redirect, url_for, send_from_directory
import sqlite3
import requests
from pdf2image import convert_from_path
import google.generativeai as genai
from concurrent.futures import ThreadPoolExecutor
import os
from PIL import Image
import traceback

app = Flask(__name__)
app.secret_key = 'your_secret_key' 

# ZeroBounce API 
ZERBOUNCE_API_KEY = ''  #  ZeroBounce API key
ZERBOUNCE_API_URL = 'https://api.zerobounce.net/v2/validate'

#  Gemini API
API_KEY = ""  #  Gemini API key
genai.configure(api_key=API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')  # Using Gemini 1.5 

# Ensure 'uploads' directory exists
if not os.path.exists('uploads'):
    os.makedirs('uploads')

# Global variables to store extracted data and file info
extracted_data = []
uploaded_file_info = None

# Database setup
def init_db():
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (firstName TEXT, lastName TEXT, email TEXT PRIMARY KEY, password TEXT)''')
    conn.commit()
    conn.close()

# Email verification function using ZeroBounce
def verify_email(email):
    try:
        params = {
            'api_key': ZERBOUNCE_API_KEY,
            'email': email
        }
        print(f"Requesting: {ZERBOUNCE_API_URL} with params: {params}")
        response = requests.get(ZERBOUNCE_API_URL, params=params)
        response.raise_for_status()
        data = response.json()
        print(f"API Response: {data}")
        status = data.get('status')
        # 'valid' means the email exists and is deliverable
        return status == 'valid'
    except requests.RequestException as e:
        print(f"Email verification error: {e}")
        return False

# Routes
@app.route('/')
def home():
    return render_template('home.html')

@app.route('/features.html')
def features():
    return render_template('features.html')

@app.route('/contact.html')
def contact():
    return render_template('contact.html')

@app.route('/about.html')
def about():
    return render_template('about.html')

@app.route('/technology.html')
def technology():
    return render_template('technology.html')

@app.route('/index')
def index():
    return render_template('index.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        data = request.get_json()
        firstName = data.get('firstName')
        lastName = data.get('lastName')
        email = data.get('email')
        password = data.get('password')

        # Validate fields
        if not firstName or not lastName or not email or not password:
            return jsonify({'message': 'All fields are required.'}), 400

        if len(password) < 8:
            return jsonify({'message': 'Password must be at least 8 characters long.'}), 400

        # Verify email
        if not verify_email(email):
            return jsonify({'message': 'Invalid or fake email address.'}), 400

        # Database connection
        conn = sqlite3.connect('users.db')
        c = conn.cursor()

        # Check if email already exists
        c.execute('SELECT email FROM users WHERE email = ?', (email,))
        if c.fetchone():
            conn.close()
            return jsonify({'message': 'Email already registered.'}), 400

        # Insert user into database
        try:
            c.execute('INSERT INTO users (firstName, lastName, email, password) VALUES (?, ?, ?, ?)',
                      (firstName, lastName, email, password))
            conn.commit()
            conn.close()
            return jsonify({'message': 'Signup successful!'}), 200
        except sqlite3.Error as e:
            conn.close()
            return jsonify({'message': 'Error saving user.'}), 500
    return render_template('signup.html')


import logging

# Create a logger
logger = logging.getLogger(__name__)

# Set the logging level
logger.setLevel(logging.DEBUG)

# Create a file handler
file_handler = logging.FileHandler('app.log')
file_handler.setLevel(logging.DEBUG)

# Create a console handler
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)

# Create a formatter and set it for the handlers
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)

# Add the handlers to the logger
logger.addHandler(file_handler)
logger.addHandler(console_handler)

# Example usage:
try:
    # Code that might raise an exception
    pass
except Exception as e:
    logger.error(f"An error occurred: {str(e)}")
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        data = request.get_json()
        email = data.get('email')
        password = data.get('password')

        conn = sqlite3.connect('users.db')
        c = conn.cursor()
        c.execute('SELECT * FROM users WHERE email = ? AND password = ?', (email, password))
        user = c.fetchone()
        conn.close()

        if user:
            session['user'] = email
            return jsonify({'message': 'Login successful!'}), 200
        else:
            return jsonify({'message': 'Invalid email or password.'}), 400
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('home'))

def extract_text_as_is(image, page_number):
    """
    Extracts the text from an image exactly as it appears using Gemini.
    """
    try:
        prompt = f"""
        Extract the text from this image exactly as it appears. Do not reformat it.
        Page Number: {page_number}
        """
        response = model.generate_content([prompt, image])
        if not response or not hasattr(response, 'text'):
            raise Exception("No valid response from Gemini API.")
        return {
            'page_number': page_number,
            'text': response.text
        }
    except Exception as e:
        print(f"Error extracting text on page {page_number}: {str(e)}")
        return {
            'page_number': page_number,
            'text': f"Error: {str(e)}"
        }

def split_into_batches(images, batch_size=5):
    """
    Splits a list of images into smaller batches for parallel processing.
    """
    for i in range(0, len(images), batch_size):
        yield images[i:i + batch_size]

def process_batch(batch, start_page):
    """
    Processes a batch of images in parallel using ThreadPoolExecutor.
    """
    with ThreadPoolExecutor() as executor:
        extracted_texts = list(
            executor.map(
                lambda img, page: extract_text_as_is(img, page),
                batch,
                range(start_page, start_page + len(batch))
            )
        )
    return extracted_texts

@app.route('/upload', methods=['POST'])
def upload_file():
    global extracted_data, uploaded_file_info

    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    upload_path = os.path.join('uploads', file.filename)
    file.save(upload_path)

    try:
        extracted_data = []
        # If PDF, convert to images and extract text
        if file.filename.lower().endswith('.pdf'):
            # Update poppler_path for your system if needed
            images = convert_from_path(upload_path, poppler_path=r'C:\poppler-24.08.0\Library\bin')
            batch_size = 5
            batches = list(split_into_batches(images, batch_size))
            start_page = 1
            for batch in batches:
                batch_texts = process_batch(batch, start_page)
                extracted_data.extend(batch_texts)
                start_page += len(batch)
            uploaded_file_info = {
                'filename': file.filename,
                'path': upload_path
            }
        else:
            # Single image case
            image = Image.open(upload_path)
            extracted_data.append(extract_text_as_is(image, 1))
            uploaded_file_info = {
                'filename': file.filename,
                'path': upload_path
            }

        return jsonify({
            'extracted_data': extracted_data,
            'uploaded_file_info': uploaded_file_info
        })
    except Exception as e:
        error_message = f"Error during file processing: {str(e)}\n{traceback.format_exc()}"
        print(error_message)
        return jsonify({'error': error_message}), 500

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory('uploads', filename)

def answer_question_with_gemini(notes, question):
    """
    Sends a prompt to Gemini instructing it to provide a well-structured answer in Markdown format.
    """
    try:
        prompt = f"""
        You have the following notes:
        {notes if notes else "No notes available."}

        Please provide a concise, well-structured answer to this question in **Markdown** format:
        {question}

        Guidelines:
        1. Use Markdown headers (##, ###) for major sections.
        2. Write explanations as paragraphs.
        3. Use '-' or '*' for bullet lists.
        4. For code blocks, enclose your code in triple backticks (
).
        5. If the answer is not available, state: "The answer is not available in the notes."
        """
        response = model.generate_content([prompt])
        if not response or not hasattr(response, 'text'):
            raise Exception("No valid response from Gemini API.")
        return response.text
    except Exception as e:
        print("Error in answer_question_with_gemini:", traceback.format_exc())
        return f"Error: {str(e)}"
    
@app.route('/delete/<filename>', methods=['DELETE'])
def delete_file(filename):
    try:
        file_path = os.path.join('uploads', filename)
        if os.path.exists(file_path):
            os.remove(file_path)
            return jsonify({'success': True, 'message': f'File {filename} deleted successfully'})
        else:
            return jsonify({'success': False, 'error': 'File not found'}), 404
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/convert-to-notes', methods=['POST'])
def convert_to_notes():
    global extracted_data

    try:
        # Combine all extracted text into a single string
        combined_text = "\n".join([f"Page {item['page_number']}:\n{item['text']}" for item in extracted_data])

        # Generate concise notes using Gemini API
        prompt = f"""
        The following text is extracted from a document. Please convert it into concise and well-structured notes that cover all the key points.
        Text:
        {combined_text}

        Guidelines:
        1. Use bullet points or numbered lists for clarity.
        2. Keep the notes short and to the point.
        3. Highlight important concepts and terms.
        4. Use Markdown formatting for headings, lists, and emphasis.
        """
        response = model.generate_content([prompt])
        if not response or not hasattr(response, 'text'):
            raise Exception("No valid response from Gemini API.")

        notes = response.text

        return jsonify({'success': True, 'notes': notes})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/ask', methods=['POST'])
def ask_question():
    global extracted_data
    data = request.json
    question = data.get('question')
    strict_mode = data.get('strict_mode', True)  # Default to strict mode (toggle button "On")

    if not question:
        return jsonify({'error': 'Question is required'}), 400

    try:
        if strict_mode and extracted_data:
            # Strict mode: Answer only from extracted data
            combined_notes = "\n".join(
                [f"Page {item['page_number']}:\n{item['text']}" for item in extracted_data]
            )
            answer = answer_question_with_gemini(combined_notes, question)
        elif not strict_mode:
            # Non-strict mode: Send request directly to Gemini
            response = model.generate_content([question])
            if not response or not hasattr(response, 'text'):
                raise Exception("No valid response from Gemini API.")
            answer = response.text
        else:
            # Strict mode is on, but no extracted data is available
            answer = "The answer is not available in the notes. Please upload a file or turn off strict mode."

        return jsonify({'answer': answer})
    except Exception as e:
        print("Exception in /ask:", traceback.format_exc())
        return jsonify({'error': str(e)}), 500
    
@app.route('/ask-bulk', methods=['POST'])
def ask_bulk_questions():
    global extracted_data
    data = request.json
    questions = data.get('questions')  # List of questions
    strict_mode = data.get('strict_mode', True)  # Default to strict mode (toggle button "On")

    if not questions or not isinstance(questions, list):
        return jsonify({'error': 'Questions must be provided as a list'}), 400

    try:
        answers = []
        for question in questions:
            if strict_mode and extracted_data:
                # Strict mode: Answer only from extracted data
                combined_notes = "\n".join(
                    [f"Page {item['page_number']}:\n{item['text']}" for item in extracted_data]
                )
                prompt = f"""
                The following text is extracted from a document. Please provide a concise and well-structured answer to this question:
                Text:
                {combined_notes}

                Question:
                {question}

                Guidelines:
                1. Use Markdown formatting for headings, lists, and emphasis.
                2. Keep the answer short and to the point.
                3. If the answer is not available, state: "The answer is not available in the notes."
                """
                response = model.generate_content([prompt])
                if not response or not hasattr(response, 'text'):
                    raise Exception("No valid response from Gemini API.")
                answer = response.text
            elif not strict_mode:
                # Non-strict mode: Send request directly to Gemini
                prompt = f"""
                Please provide a concise and well-structured answer to this question:
                Question:
                {question}

                Guidelines:
                1. Use Markdown formatting for headings, lists, and emphasis.
                2. Keep the answer short and to the point.
                """
                response = model.generate_content([prompt])
                if not response or not hasattr(response, 'text'):
                    raise Exception("No valid response from Gemini API.")
                answer = response.text
            else:
                # Strict mode is on, but no extracted data is available
                answer = "The answer is not available in the notes. Please upload a file or turn off strict mode."

            answers.append(answer)

        return jsonify({'answers': answers})
    except Exception as e:
        print("Exception in /ask-bulk:", traceback.format_exc())
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    init_db()
    app.run(debug=True, port=5000)
