#!/usr/bin/python3
# v179_web.py - Web server version of v179.py for SVG to 3MF conversion
import os
import sys
import time
import webbrowser
import threading
import socketserver
from web_handler import WebRequestHandler

def run_server(port=8000):
    """Run the HTTP server"""
    # Try to use the specified port, if it fails try the next port
    for attempt in range(10):  # Try up to 10 different ports
        try:
            current_port = port + attempt
            with socketserver.TCPServer(("localhost", current_port), WebRequestHandler) as httpd:
                print(f"Server running at http://localhost:{current_port}")
                print(f"Press Ctrl+C to stop the server")
                # Open browser in a separate thread
                threading.Thread(target=lambda: open_browser(current_port), daemon=True).start()
                # Serve forever
                httpd.serve_forever()
        except OSError as e:
            print(f"Port {current_port} is busy, trying next port...")
        except Exception as e:
            print(f"Error starting server: {str(e)}")
            break

def open_browser(port=8000):
    """Open the web browser"""
    # Wait a moment for the server to start
    time.sleep(1)
    # Open browser
    try:
        webbrowser.open(f"http://localhost:{port}")
    except Exception as e:
        print(f"Error opening browser: {str(e)}")
        print(f"Please open your browser and navigate to: http://localhost:{port}")

def check_template_file():
    """Check if the template file exists, if not, create it"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    template_path = os.path.join(script_dir, "template.html")
    
    print(f"Looking for template file at: {template_path}")
    
    if not os.path.exists(template_path):
        print("Template file not found. Please make sure template.html is in the same directory as this script.")
        return False
    return True

def main():
    """Main entry point"""
    # Print helpful debug info
    print(f"Current working directory: {os.getcwd()}")
    print(f"Script location: {os.path.abspath(__file__)}")
    
    print("\nSVG to 3MF Converter v179 - Web Edition")
    print("----------------------------------------------------------------")
    print("This tool allows you to set specific heights, filaments, and wall loops for each layer.\n")
    
    # Check if template exists
    if not check_template_file():
        print("\nERROR: template.html file not found.")
        print("Please make sure template.html is in the same directory as this script.")
        sys.exit(1)
    
    port = 8000
    print("Starting web server...")
    print("The web interface will open in your browser.")
    
    # Start server
    run_server(port)

if __name__ == "__main__":
    main()
