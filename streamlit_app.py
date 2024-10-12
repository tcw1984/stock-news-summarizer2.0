# Install necessary packages if needed
import subprocess
subprocess.run(['pip', 'install', 'groq', 'gradio', 'beautifulsoup4', 'yfinance', 'streamlit', 'python-dotenv'])

import os
import requests
from groq import Groq, APIError
from bs4 import BeautifulSoup
import streamlit as st
from datetime import datetime, timedelta
import yfinance as yf
import pandas as pd
import time
import re
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Fetch the Groq API Key from environment variables
API_KEY = os.getenv("GROQ_API_KEY")
if not API_KEY:
    raise ValueError("GROQ_API_KEY not found. Please add it to the .env file.")

# Initialize Groq client
client = Groq(api_key=API_KEY)

# Function to fetch the full article content
def fetch_article_content(article_url):
    try:
        response = requests.get(article_url)
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            # Extract article content from <p> tags
            article_body = soup.find_all('p')
            article_text = ' '.join([p.get_text() for p in article_body])
            return article_text.strip()
        else:
            return "Unable to retrieve article content."
    except Exception as e:
        return f"Error retrieving content: {e}"

# Function to fetch news articles from Bing News RSS and extract content
def fetch_bing_news_and_content(company_name, interval, seen_articles=None):
    if seen_articles is None:
        seen_articles = set()

    articles = []
    query = f"{company_name}"
    base_url = f'https://www.bing.com/news/search?q={query}&qft=interval%3d%22{interval}%22&form=PTFTNR&format=rss'

    response = requests.get(base_url)
    soup = BeautifulSoup(response.content, 'xml')

    items = soup.find_all('item')

    for item in items:
        try:
            title = item.title.text
            link = item.link.text
            pub_date_str = item.pubDate.text
            pub_date = datetime.strptime(pub_date_str, '%a, %d %b %Y %H:%M:%S %Z').date()

            article_key = (title, link)
            if article_key not in seen_articles:
                # Fetch and store the article content
                article_content = fetch_article_content(link)
                articles.append((pub_date, title, link, article_content))
                seen_articles.add(article_key)
        except Exception as e:
            print(f"Error processing article: {e}")

    return articles

# Function to summarize articles based on their content
def summarize_articles(articles):
    max_model_tokens = 8192
    max_output_tokens = 512
    max_tokens_per_minute = 7000
    estimated_tokens_per_char = 1 / 4

    summaries = []
    batch_articles = articles.copy()
    while batch_articles:
        num_articles = len(batch_articles)
        while num_articles > 0:
            batch = batch_articles[:num_articles]
            summary_input = "\n".join([content for _, _, _, content in batch])  # Use the article content

            input_tokens = int(len(summary_input) * estimated_tokens_per_char)
            total_tokens = input_tokens + max_output_tokens

            if total_tokens <= min(max_model_tokens, max_tokens_per_minute):
                try:
                    completion = client.chat.completions.create(
                        model="llama-3.2-90b-text-preview",
                        messages=[{'role': 'user', 'content': f"Summarize key updates or issues of the company based on the following articles:\n{summary_input}"}],
                        temperature=1,
                        max_tokens=max_output_tokens,
                        top_p=1,
                        stream=False,
                        stop=None,
                    )
                    summary = completion.choices[0].message.content.strip()
                    summaries.append(summary)
                    batch_articles = batch_articles[num_articles:]
                    break
                except APIError as e:
                    error_message = str(e)
                    if 'rate_limit_exceeded' in error_message:
                        wait_time_match = re.search(r'Please try again in ([\d.]+)s', error_message)
                        wait_time = float(wait_time_match.group(1)) + 1 if wait_time_match else 60
                        print(f"Rate limit exceeded. Waiting for {wait_time} seconds before retrying...")
                        time.sleep(wait_time)
                    elif 'context_length_exceeded' in error_message or 'Please reduce the length of the messages or completion' in error_message:
                        print("Context length exceeded. Reducing batch size...")
                        num_articles -= 1
                    else:
                        print(f"Error generating summary: {error_message}")
                        return "\n\n".join(summaries)
            else:
                num_articles -= 1

        if num_articles == 0:
            print("Unable to process articles due to size limitations.")
            break

    final_summary = "\n\n".join(summaries)
    return final_summary

# Function to summarize stock news and article content
def summarize_stock_news_content(ticker, interval):
    try:
        stock = yf.Ticker(ticker)
        company_name = stock.info.get('longName', '')
        if not company_name:
            return "Invalid stock ticker."
    except Exception:
        return "Failed to retrieve company information."

    articles = fetch_bing_news_and_content(company_name, interval)

    if not articles:
        return "No articles found."

    # Use the summarize_articles function instead of summarize_articles_content
    summary = summarize_articles(articles)

    return summary

# Streamlit UI setup
st.title("Stock News Summarizer 2.0")

# Correct password stored in .env file for security
correct_password = os.getenv("APP_PASSWORD")

# Create a password input field
password = st.text_input("Enter Password", type="password")

# Check if the password is correct
if password == correct_password:
    st.success("Password correct! You can now use the app.")
    
    # Input fields for stock ticker
    ticker = st.text_input("Stock Ticker", "NVDA")
    
    # Time options: 24 hours, 7 days, or 30 days
    time_range = st.selectbox("Select Time Range", ["Past 24 hours", "Past 7 days", "Past 30 days"])

    # Convert user selection to Bing's query format
    if time_range == "Past 24 hours":
        interval = "7"
    elif time_range == "Past 7 days":
        interval = "8"
    else:
        interval = "9"

    # Summarize button
    if st.button("Summarize"):
        summary = summarize_stock_news_content(ticker, interval)
        
        # Display the summary
        st.write(summary)

        # Add the Copy button with JavaScript to copy the text to the clipboard
        copy_button = f"""
        <button onclick="copyToClipboard()">
            Copy to Clipboard
        </button>
        <script>
            function copyToClipboard() {{
                if (navigator.clipboard) {{
                    navigator.clipboard.writeText(`{summary}`).then(function() {{
                        alert('Copied to clipboard!');
                    }}, function(err) {{
                        alert('Could not copy text: ', err);
                    }});
                }} else {{
                    // Fallback for older browsers
                    var textArea = document.createElement("textarea");
                    textArea.value = `{summary}`;
                    document.body.appendChild(textArea);
                    textArea.select();
                    try {{
                        document.execCommand('copy');
                        alert('Copied to clipboard!');
                    }} catch
