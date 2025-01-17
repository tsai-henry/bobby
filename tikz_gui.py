import customtkinter as ctk
import os
from openai import OpenAI
import tempfile
import subprocess
from PIL import Image, ImageTk
from pdf2image import convert_from_path
import re
import threading
import queue
import logging
import sys

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('tikz_gui.log')
    ]
)

class MessageBubble(ctk.CTkFrame):
    def __init__(self, parent, message, is_user=True):
        super().__init__(parent, fg_color="transparent")
        
        # Configure grid
        self.grid_columnconfigure(1 if is_user else 0, weight=1)
        self.grid_columnconfigure(0 if is_user else 1, weight=2)  # More space on the opposite side
        
        # Create message label with word wrap
        bubble_color = "#2D5AF7" if is_user else "#383B42"  # Blue for user, darker gray for assistant
        text_color = "white"  # Always white text for dark theme
        
        # Calculate appropriate height based on message length
        line_length = 60  # characters per line
        num_lines = (len(message) // line_length) + message.count('\n') + 1
        estimated_height = max(25, min(300, num_lines * 20))  # min height 25, max 300
        
        self.message = ctk.CTkTextbox(
            self,
            wrap="word",
            height=estimated_height,
            width=min(400, len(message) * 8),  # Dynamic width based on content
            fg_color=bubble_color,
            text_color=text_color,
            corner_radius=15,
            activate_scrollbars=False
        )
        
        # Insert and configure text
        self.message.insert("1.0", message)
        self.message.configure(state="disabled")
        
        # Position the bubble
        col = 1 if is_user else 0
        self.message.grid(
            row=0,
            column=col,
            padx=(20 if not is_user else 60, 60 if is_user else 20),
            pady=5,
            sticky="ew"
        )

class ChatFrame(ctk.CTkScrollableFrame):
    def __init__(self, parent):
        super().__init__(
            parent,
            fg_color="#1E1E1E",  # Dark background
            corner_radius=15
        )
        self.grid_columnconfigure(0, weight=1)
    
    def add_message(self, message, is_user=True):
        # Add some spacing between messages
        if len(self.grid_slaves()) > 0:
            spacer = ctk.CTkFrame(self, fg_color="transparent", height=5)
            spacer.grid(row=len(self.grid_slaves()), column=0, sticky="ew")
        
        bubble = MessageBubble(self, message, is_user)
        bubble.grid(row=len(self.grid_slaves()), column=0, sticky="ew")
        
        # Scroll to bottom
        self.after(100, self._scroll_to_bottom)
    
    def _scroll_to_bottom(self):
        self._parent_canvas.yview_moveto(1.0)

class CodeView(ctk.CTkTextbox):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.configure(
            font=("Courier", 14),
            fg_color="#282C34",  # Dark background
            text_color="#ABB2BF",  # Light gray text
            wrap="none",  # No text wrapping for code
            padx=10,
            pady=10
        )
        
        # Initialize syntax highlighting colors
        self.tag_config("command", foreground="#C678DD")    # Purple for commands
        self.tag_config("comment", foreground="#98C379")    # Green for comments
        self.tag_config("brackets", foreground="#E5C07B")   # Yellow for brackets
        self.tag_config("numbers", foreground="#61AFEF")    # Blue for numbers
        self.tag_config("curly", foreground="#56B6C2")      # Cyan for curly braces
        
        # Compile regex patterns
        self.patterns = {
            "command": re.compile(r"\\[a-zA-Z]+"),
            "comment": re.compile(r"%[^\n]*"),
            "brackets": re.compile(r"\[[^\]]*\]"),
            "numbers": re.compile(r"\b\d+\.?\d*\b"),
            "curly": re.compile(r"[{}]")
        }
        
        # Add key bindings for editing
        self.bind("<KeyRelease>", self.on_edit)
        
        # Add debounce for live preview
        self.update_timer = None
        self.update_delay = 500  # ms
    
    def set_code(self, code):
        self.configure(state="normal")
        self.delete("1.0", "end")
        self.insert("1.0", code)
        self.highlight_syntax()
    
    def highlight_syntax(self):
        # Process highlighting in chunks
        for tag, pattern in self.patterns.items():
            self.tag_remove(tag, "1.0", "end")
            start = "1.0"
            while True:
                # Search for pattern
                match = pattern.search(self.get(start, "end"))
                if not match:
                    break
                
                # Convert match position to text widget index
                match_start = f"{start}+{match.start()}c"
                match_end = f"{start}+{match.end()}c"
                
                # Add tag
                self.tag_add(tag, match_start, match_end)
                
                # Move to next position
                start = match_end
    
    def on_edit(self, event):
        # Cancel previous timer if it exists
        if self.update_timer is not None:
            self.after_cancel(self.update_timer)
        
        # Start new timer
        self.update_timer = self.after(self.update_delay, self.update_preview)
        
        # Update syntax highlighting immediately
        self.highlight_syntax()
    
    def update_preview(self):
        # Get current code
        code = self.get("1.0", "end-1c")
        
        # Tell parent to update preview
        if hasattr(self, "parent_gui"):
            self.parent_gui.render_tikz_async(code)
    
    def set_parent_gui(self, gui):
        self.parent_gui = gui

class LoadingIndicator(ctk.CTkLabel):
    def __init__(self, parent):
        super().__init__(
            parent,
            text="",
            fg_color="#2B2B2B",
            corner_radius=10,
            width=50,
            height=20,
            text_color="#FFFFFF"
        )
        self.dots = 0
        self.is_running = False
    
    def start(self):
        self.is_running = True
        self.update_dots()
        self.grid()
    
    def stop(self):
        self.is_running = False
        self.grid_remove()
    
    def update_dots(self):
        if not self.is_running:
            return
        self.dots = (self.dots + 1) % 4
        self.configure(text="." * self.dots)
        self.after(500, self.update_dots)

class TikZGUI:
    def __init__(self):
        logging.info("Initializing TikZGUI")
        self.root = ctk.CTk()
        self.root.title("TikZ Diagram Generator")
        self.root.geometry("1200x800")
        
        # Set theme
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        
        # Initialize NVIDIA API client
        logging.info("Initializing NVIDIA API client")
        try:
            self.client = OpenAI(
                base_url="https://integrate.api.nvidia.com/v1",
                api_key="***REMOVED***"
            )
            logging.info("NVIDIA API client initialized successfully")
        except Exception as e:
            logging.error(f"Failed to initialize NVIDIA API client: {str(e)}", exc_info=True)
            raise
        
        self.current_code = ""
        self.show_chat = True
        self.result_queue = queue.Queue()
        
        self.create_gui_elements()
        
        # Configure grid weights
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(0, weight=1)
        
        # Start result checker
        self.check_results()
        logging.info("TikZGUI initialization complete")
    
    def create_gui_elements(self):
        # Main content frame (top part)
        content_frame = ctk.CTkFrame(self.root, fg_color="#1E1E1E")
        content_frame.grid(row=0, column=0, columnspan=2, sticky="nsew", padx=10, pady=(10, 0))
        content_frame.grid_columnconfigure(0, weight=1)
        content_frame.grid_columnconfigure(1, weight=1)
        content_frame.grid_rowconfigure(0, weight=1)
        
        # Left Panel (Code/Chat View)
        self.left_frame = ctk.CTkFrame(content_frame, fg_color="#1E1E1E")
        self.left_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        self.left_frame.grid_rowconfigure(1, weight=1)
        self.left_frame.grid_columnconfigure(0, weight=1)
        
        # Create top bar with toggle button
        top_bar = ctk.CTkFrame(self.left_frame, fg_color="#2B2B2B", height=40)
        top_bar.grid(row=0, column=0, sticky="ew", pady=(0, 5))
        top_bar.grid_propagate(False)
        
        self.toggle_button = ctk.CTkButton(
            top_bar,
            text="Show Code",
            command=self.toggle_view,
            width=100,
            height=30,
            corner_radius=15,
            fg_color="#2D5AF7",
            hover_color="#1E3EAC"
        )
        self.toggle_button.place(relx=0.5, rely=0.5, anchor="center")
        
        # Create both chat and code views
        self.chat_frame = ChatFrame(self.left_frame)
        self.code_view = CodeView(self.left_frame)
        self.code_view.set_parent_gui(self)
        
        # Initially show chat view
        self.chat_frame.grid(row=1, column=0, sticky="nsew")
        
        # Right Panel (Diagram Display)
        right_frame = ctk.CTkFrame(content_frame, fg_color="#1E1E1E")
        right_frame.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        right_frame.grid_columnconfigure(0, weight=1)
        right_frame.grid_rowconfigure(0, weight=1)
        
        # White canvas for diagram display
        canvas_frame = ctk.CTkFrame(right_frame, fg_color="white", corner_radius=15)
        canvas_frame.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        canvas_frame.grid_columnconfigure(0, weight=1)
        canvas_frame.grid_rowconfigure(0, weight=1)
        
        self.canvas = ctk.CTkCanvas(canvas_frame, bg="white", highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        
        # Loading indicator
        self.loading_indicator = LoadingIndicator(right_frame)
        self.loading_indicator.grid(row=1, column=0, padx=10, pady=10)
        
        # Bottom input area (centered)
        input_frame = ctk.CTkFrame(self.root, fg_color="#2B2B2B", corner_radius=15, height=90)
        input_frame.grid(row=1, column=0, columnspan=2, sticky="ew", padx=200, pady=10)
        input_frame.grid_propagate(False)
        input_frame.grid_columnconfigure(0, weight=1)
        
        self.input_text = ctk.CTkTextbox(
            input_frame,
            height=50,
            wrap="word",
            fg_color="#383B42",
            text_color="gray70",  # Start with translucent text
            border_width=0,
            corner_radius=10
        )
        self.input_text.insert("1.0", "Describe the diagram you want to create...")
        self.input_text.bind("<FocusIn>", lambda e: self.on_input_focus_in())
        self.input_text.bind("<FocusOut>", lambda e: self.on_input_focus_out())
        self.input_text.bind("<Return>", lambda e: self.on_enter_pressed(e))
        self.input_text.bind("<Key>", lambda e: self.on_key_press(e))
        self.input_text.grid(row=0, column=0, sticky="ew", padx=10, pady=(20, 20))
        
        # Send button
        send_button = ctk.CTkButton(
            input_frame,
            text="Draw",
            command=self.generate_diagram,
            width=80,
            height=35,
            corner_radius=17,
            fg_color="#2D5AF7",
            hover_color="#1E3EAC"
        )
        send_button.grid(row=0, column=1, padx=10, pady=5)
        
        # Configure root grid
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(0, weight=1)
        
        # Add welcome message
        self.chat_frame.add_message("Welcome! Describe the diagram you want to create.", is_user=False)
    
    def toggle_view(self):
        self.show_chat = not self.show_chat
        if self.show_chat:
            self.code_view.grid_remove()
            self.chat_frame.grid(row=1, column=0, sticky="nsew")
            self.toggle_button.configure(text="Show Code")
        else:
            self.chat_frame.grid_remove()
            self.code_view.grid(row=1, column=0, sticky="nsew")
            self.toggle_button.configure(text="Show Chat")
            # Set current code in editor
            if self.current_code:
                self.code_view.set_code(self.current_code)
    
    def on_input_focus_in(self):
        if self.input_text.get("1.0", "end-1c") == "Describe the diagram you want to create...":
            self.input_text.delete("1.0", "end")
            self.input_text.configure(text_color="white")  # Reset to full opacity
    
    def on_input_focus_out(self):
        if not self.input_text.get("1.0", "end-1c").strip():
            self.input_text.delete("1.0", "end")
            self.input_text.insert("1.0", "Describe the diagram you want to create...")
            self.input_text.configure(text_color="gray70")  # Make placeholder text translucent
    
    def on_key_press(self, event):
        # If it's the first keypress and the placeholder is still there, clear it
        if self.input_text.get("1.0", "end-1c") == "Describe the diagram you want to create...":
            self.input_text.delete("1.0", "end")
            self.input_text.configure(text_color="white")  # Reset to full opacity
    
    def on_enter_pressed(self, event):
        if event.state == 0:  # No modifiers (Shift, Control, etc.)
            self.generate_diagram()
            return "break"  # Prevents the newline from being inserted
    
    def generate_diagram(self):
        # Get input text
        user_input = self.input_text.get("1.0", "end-1c").strip()
        if not user_input or user_input == "Describe the diagram you want to create...":
            return
        
        # Clear input
        self.input_text.delete("1.0", "end")
        self.input_text.insert("1.0", "Describe the diagram you want to create...")
        self.input_text.configure(text_color="gray70")
        
        # Add user message to chat
        self.chat_frame.add_message(user_input, is_user=True)
        
        # Prepare messages for API
        messages = [
            {"role": "system", "content": """Generate ONLY valid TikZ code. Your response must follow this EXACT format:

\begin{tikzpicture}
% Your TikZ commands here
\end{tikzpicture}

Rules:
1. Keep it simple - just basic shapes and lines
2. Use standard colors (red, blue, green, etc.)
3. Center components at (0,0)
4. No scaling or transformations
5. No shadows or fancy effects

DO NOT add ANY text before or after the code."""},
            {"role": "user", "content": user_input}
        ]
        
        # Start loading indicator
        self.loading_indicator.start()
        
        # Clear previous diagram
        self.canvas.delete("all")
        
        # Start async task
        threading.Thread(target=self.generate_diagram_async, args=(messages,)).start()
    
    def generate_diagram_async(self, messages):
        try:
            # Stream the response
            response_started = False
            tikz_code = ""
            
            logging.info("Making API request to NVIDIA")
            logging.debug(f"Request messages: {messages}")
            
            try:
                completion = self.client.chat.completions.create(
                    model="meta/llama-3.3-70b-instruct",
                    messages=messages,
                    temperature=0.01,
                    top_p=0.7,
                    max_tokens=1024,  # Increased for more complex diagrams
                    stream=True
                )
                logging.info("API request successful")
            except Exception as e:
                logging.error(f"API request failed: {str(e)}", exc_info=True)
                if hasattr(e, 'response'):
                    logging.error(f"Response status: {e.response.status_code}")
                    logging.error(f"Response body: {e.response.text}")
                raise
            
            try:
                for chunk in completion:
                    if chunk.choices[0].delta.content:
                        tikz_code += chunk.choices[0].delta.content
                        if not response_started:
                            logging.info("Started receiving response chunks")
                            response_started = True
                        self.root.update()
                
                logging.info("Finished receiving response")
                logging.debug(f"Final TikZ code: {tikz_code}")
                
                # Clean up the code
                tikz_code = self.clean_tikz_code(tikz_code)
                
                # Put result in queue
                self.result_queue.put(tikz_code)
            
            except Exception as e:
                logging.error(f"Error processing response chunks: {str(e)}", exc_info=True)
                raise
        
        except Exception as e:
            logging.error(f"Error in generate_diagram_async: {str(e)}", exc_info=True)
            # Put exception in queue
            self.result_queue.put(e)
    
    def clean_tikz_code(self, code):
        """Clean and validate TikZ code."""
        # Remove backticks and language markers
        code = re.sub(r'```(?:tikz)?\n?', '', code)
        code = code.strip()
        
        # Ensure proper tikzpicture environment
        if not "\\begin{tikzpicture}" in code:
            code = "\\begin{tikzpicture}\n" + code
        
        if not "\\end{tikzpicture}" in code:
            code = code + "\n\\end{tikzpicture}"
        
        logging.info("Cleaned TikZ code")
        logging.debug(f"Clean code: {code}")
        
        return code
        
    def render_tikz(self, tikz_code):
        try:
            logging.info("Starting TikZ rendering")
            logging.debug(f"Rendering code: {tikz_code}")
            
            # Create a temporary directory
            with tempfile.TemporaryDirectory() as temp_dir:
                logging.debug(f"Created temp directory: {temp_dir}")
                
                # Write the complete LaTeX document
                tex_path = os.path.join(temp_dir, "diagram.tex")
                with open(tex_path, "w") as f:
                    latex_doc = """\\documentclass[tikz,border=10pt]{standalone}
\\usepackage{tikz}
\\begin{document}
""" + tikz_code + """
\\end{document}"""
                    f.write(latex_doc)
                logging.debug(f"Wrote LaTeX file: {tex_path}")
                
                # Compile LaTeX to PDF
                logging.info("Running pdflatex")
                result = subprocess.run(["pdflatex", "-output-directory", temp_dir, tex_path], 
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                
                if result.returncode != 0:
                    error_msg = f"pdflatex failed with code {result.returncode}\n"
                    error_msg += f"STDOUT:\n{result.stdout}\n"
                    error_msg += f"STDERR:\n{result.stderr}"
                    raise Exception(error_msg)
                
                # Convert PDF to image
                pdf_path = os.path.join(temp_dir, "diagram.pdf")
                if not os.path.exists(pdf_path):
                    raise Exception(f"PDF file not created at {pdf_path}")
                
                logging.info("Converting PDF to image")
                images = convert_from_path(pdf_path)
                
                if images:
                    logging.info("Successfully converted PDF to image")
                    image = images[0]
                    self.root.after(0, lambda: self.update_canvas_with_image(image))
                else:
                    raise Exception("Failed to convert PDF to image")
                    
        except Exception as e:
            logging.error(f"Error in render_tikz: {str(e)}", exc_info=True)
            def show_error():
                error_message = f"Error rendering diagram: {str(e)}"
                self.chat_frame.add_message(error_message, is_user=False)
            self.root.after(0, show_error)
    
    def render_tikz_async(self, tikz_code):
        # Start async task
        threading.Thread(target=self.render_tikz, args=(tikz_code,)).start()
    
    def update_canvas_with_image(self, image):
        # Clear previous image
        self.canvas.delete("all")
        
        # Get canvas dimensions
        canvas_width = self.canvas.winfo_width()
        canvas_height = self.canvas.winfo_height()
        
        if canvas_width > 1 and canvas_height > 1:  # Canvas has been rendered
            # Calculate scale to fit while maintaining aspect ratio
            scale = min(
                (canvas_width - 20) / image.width,  # Leave 10px padding on each side
                (canvas_height - 20) / image.height
            )
            
            if scale < 1:
                new_size = (int(image.width * scale), int(image.height * scale))
                image_resized = image.resize(new_size, Image.Resampling.LANCZOS)
            else:
                image_resized = image
            
            # Convert to PhotoImage
            photo = ImageTk.PhotoImage(image_resized)
            
            # Calculate position to center the image
            x = (canvas_width - photo.width()) // 2
            y = (canvas_height - photo.height()) // 2
            
            # Create image on canvas
            self.canvas.create_image(x, y, image=photo, anchor="nw")
            # Keep a reference to prevent garbage collection
            self.canvas._photo = photo
            
            logging.info("Successfully updated canvas with new image")
    
    def update_ui_with_result(self, result):
        tikz_code = result
        
        # Store and display the code
        self.current_code = tikz_code
        if not self.show_chat:
            self.code_view.set_code(tikz_code)
        
        # Show in chat if in chat view
        if self.show_chat:
            self.chat_frame.add_message(tikz_code, is_user=False)
        
        # Render TikZ code
        self.render_tikz_async(tikz_code)
        
        # Stop loading indicator
        self.loading_indicator.stop()
    
    def check_results(self):
        try:
            while True:
                result = self.result_queue.get_nowait()
                if isinstance(result, Exception):
                    self.chat_frame.add_message(f"Error: {str(result)}", is_user=False)
                    self.loading_indicator.stop()
                else:
                    self.update_ui_with_result(result)
                self.result_queue.task_done()
        except queue.Empty:
            pass
        finally:
            self.root.after(100, self.check_results)

def main():
    app = TikZGUI()
    app.root.mainloop()

if __name__ == "__main__":
    main()
