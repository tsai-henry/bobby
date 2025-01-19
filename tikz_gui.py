import os
import logging
import queue
import threading
import customtkinter as ctk
from PIL import Image
import re
from datetime import datetime
from openai import OpenAI
import tempfile
import subprocess
from PIL import Image, ImageTk
from pdf2image import convert_from_path
import sys
from dotenv import load_dotenv
import asyncio
import shutil

# Global Constants and Configuration
WINDOW_SIZE = "1800x1200"
WINDOW_TITLE = "Bobby"
UPDATE_DELAY = 500  # ms for code preview updates
LINE_LENGTH = 60  # characters per line for message bubbles
LOADING_INTERVAL = 700  # ms between loading indicator updates
MIN_BUBBLE_WIDTH = 50  # minimum width for message bubbles
CHARS_PER_WIDTH_UNIT = 1  # number of characters per width unit
MAX_BUBBLE_WIDTH = 300  # maximum width for message bubbles
FONT_SIZE = 18  # base font size for text
LOADING_SIZE = 20  # size of loading indicator
CHAT_WIDTH = 500  # width of chat frame

# UI Colors
DARK_BG = "#1E1E1E"
CODE_BG = "#282C34"
CODE_TEXT = "#ABB2BF"
USER_BUBBLE_COLOR = "#2D5AF7"
ASSISTANT_BUBBLE_COLOR = "#383B42"
LOADING_FG = "#2D5AF7"

# Syntax Highlighting Colors
COMMAND_COLOR = "#C678DD"    # Purple for commands
COMMENT_COLOR = "#98C379"    # Green for comments
BRACKETS_COLOR = "#E5C07B"   # Yellow for brackets
NUMBERS_COLOR = "#61AFEF"    # Blue for numbers
CURLY_COLOR = "#56B6C2"      # Cyan for curly braces

# Regex Patterns for Syntax Highlighting
SYNTAX_PATTERNS = {
    "command": re.compile(r"\\[a-zA-Z]+"),
    "comment": re.compile(r"%[^\n]*"),
    "brackets": re.compile(r"\[[^\]]*\]"),
    "numbers": re.compile(r"\b\d+\.?\d*\b"),
    "curly": re.compile(r"[{}]")
}

# System Prompts
PROMPT_GENERATOR_SYSTEM_PROMPT = """You are an expert in creating detailed prompts for TikZ diagram generation.
Your task is to take a user's request and create a more detailed and specific prompt that will help generate high-quality TikZ diagrams.
Consider the following aspects when creating the prompt:
1. Specific visual elements and their relationships
2. Styling requirements (colors, line styles, etc.)
3. Layout and positioning preferences
4. Required TikZ libraries and features
5. Any mathematical or technical requirements

Output ONLY the detailed prompt without any explanations or additional text."""

TIKZ_SYSTEM_PROMPT = """You are an expert in TikZ, a powerful drawing tool for LaTeX. Your task is to help users create 
TikZ diagrams based on their descriptions. Follow these guidelines:
1. Generate ONLY valid TikZ code. Your response must follow this EXACT format:
\begin{tikzpicture}
% Your TikZ commands here
\end{tikzpicture}
2. Use appropriate TikZ libraries when needed
3. Keep the code clean and well-commented
4. Ensure the diagram fits within reasonable dimensions
"""

# Load environment variables
load_dotenv() 

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
        self.grid_columnconfigure(0 if is_user else 1, weight=2)
        
        # Create message label
        self.message = ctk.CTkLabel(
            self,
            text=message,
            wraplength=MAX_BUBBLE_WIDTH,
            fg_color=USER_BUBBLE_COLOR if is_user else ASSISTANT_BUBBLE_COLOR,
            text_color="white",
            corner_radius=15,
            font=("Helvetica", FONT_SIZE),
            justify="left",
            padx=10,
            pady=5
        )
        
        # Position the bubble
        self.message.grid(
            row=0,
            column=1 if is_user else 0,
            padx=(5 if not is_user else 0, 0 if is_user else 5),
            pady=2,
            sticky="e" if is_user else "w"
        )

class ChatFrame(ctk.CTkScrollableFrame):
    def __init__(self, parent):
        super().__init__(parent, fg_color=DARK_BG)
        self.grid_columnconfigure(0, weight=1)
        self.messages = []
        
        # Loading indicator at bottom
        self.loading_frame = ctk.CTkFrame(self, fg_color=DARK_BG, height=30)
        self.loading_frame.grid(row=1000, column=0, sticky="ew", pady=(5, 0))  # High row number to keep at bottom
        self.loading_frame.grid_columnconfigure(0, weight=1)
        self.loading_frame.grid_propagate(False)
        
        self.loading_indicator = LoadingIndicator(self.loading_frame)
        self.loading_indicator.grid(row=0, column=0)
        self.loading_indicator.grid_remove()  # Hidden by default

    def add_message(self, text, is_user=False):
        # Create message bubble
        bubble = MessageBubble(self, text, is_user)
        row = len(self.messages)
        bubble.grid(row=row, column=0, sticky="ew", pady=(0, 10))
        self.messages.append(bubble)
        self.smooth_scroll_to_bottom()
    
    def start_loading(self):
        self.loading_indicator.grid()
        self.loading_indicator.start()
        self.smooth_scroll_to_bottom()
    
    def stop_loading(self):
        self.loading_indicator.stop()
        self.loading_indicator.grid_remove()

    def smooth_scroll_to_bottom(self):
        """Smoothly scroll to the bottom of the chat"""
        try:
            current = float(self._parent_canvas.yview()[1])
            if abs(1.0 - current) > 0.01:
                next_pos = current + (1.0 - current) * 0.3
                self._parent_canvas.yview_moveto(next_pos)
                self.after(20, self.smooth_scroll_to_bottom)
            else:
                self._parent_canvas.yview_moveto(1.0)
        except Exception as e:
            logging.error(f"Scroll error: {str(e)}")
            self._parent_canvas.yview_moveto(1.0)

class CodeView(ctk.CTkTextbox):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.configure(
            font=("Courier", FONT_SIZE),
            fg_color=CODE_BG,  # Dark background
            text_color=CODE_TEXT,  # Light gray text
            wrap="none",  # No text wrapping for code
            padx=10,
            pady=10
        )
        
        # Initialize syntax highlighting colors
        self.tag_config("command", foreground=COMMAND_COLOR)    # Purple for commands
        self.tag_config("comment", foreground=COMMENT_COLOR)    # Green for comments
        self.tag_config("brackets", foreground=BRACKETS_COLOR)   # Yellow for brackets
        self.tag_config("numbers", foreground=NUMBERS_COLOR)    # Blue for numbers
        self.tag_config("curly", foreground=CURLY_COLOR)      # Cyan for curly braces
        
        # Compile regex patterns
        self.patterns = SYNTAX_PATTERNS
        
        # Add key bindings for editing
        self.bind("<KeyRelease>", self.on_edit)
        
        # Add debounce for live preview
        self.update_timer = None
        self.update_delay = UPDATE_DELAY  # ms
    
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

class LoadingIndicator:
    def __init__(self, parent):
        self.frame = ctk.CTkFrame(parent, fg_color="transparent", width=LOADING_SIZE, height=LOADING_SIZE)
        self.canvas = ctk.CTkCanvas(
            self.frame,
            width=LOADING_SIZE,
            height=LOADING_SIZE,
            bg="#2B2B2B",
            highlightthickness=0
        )
        self.canvas.place(relx=0.5, rely=0.5, anchor="center")
        self.angle = 0
        self.running = False
        
    def draw_spinner(self):
        size = LOADING_SIZE
        center = size / 2
        radius = (size - 4) / 2  # Slightly smaller than canvas
        
        # Clear previous drawing
        self.canvas.delete("spinner")
        
        # Draw arc
        start_angle = self.angle
        extent = 300  # Leave a gap in the circle
        
        # Create gradient effect with multiple arcs
        width = 3
        segments = 8
        for i in range(segments):
            seg_extent = extent / segments
            seg_start = start_angle + (i * seg_extent)
            opacity = 0.3 + (0.7 * i / segments)  # Fade from 0.3 to 1.0
            color = self._get_color_with_opacity(USER_BUBBLE_COLOR, opacity)
            
            self.canvas.create_arc(
                2, 2, size-2, size-2,
                start=seg_start,
                extent=seg_extent,
                width=width,
                outline=color,
                style="arc",
                tags="spinner"
            )
        
        if self.running:
            self.angle = (self.angle + 10) % 360
            self.canvas.after(50, self.draw_spinner)
    
    def _get_color_with_opacity(self, color, opacity):
        # Convert hex color to RGB values
        r = int(color[1:3], 16)
        g = int(color[3:5], 16)
        b = int(color[5:7], 16)
        # For Tkinter, we need to use standard color names or #RRGGBB format
        # We'll blend with background color instead of using opacity
        bg_color = (43, 43, 43)  # #2B2B2B background
        blended_r = int(r * opacity + bg_color[0] * (1 - opacity))
        blended_g = int(g * opacity + bg_color[1] * (1 - opacity))
        blended_b = int(b * opacity + bg_color[2] * (1 - opacity))
        return f"#{blended_r:02x}{blended_g:02x}{blended_b:02x}"
    
    def start(self):
        if not self.running:
            self.running = True
            self.draw_spinner()
    
    def stop(self):
        self.running = False
        self.canvas.delete("spinner")
    
    def grid(self, *args, **kwargs):
        self.frame.grid(*args, **kwargs)
    
    def grid_remove(self):
        self.frame.grid_remove()
    
    def grid_forget(self):
        self.frame.grid_forget()

class TikZGUI:
    def __init__(self):
        logging.info("Initializing TikZGUI")
        self.root = ctk.CTk()
        self.root.title(WINDOW_TITLE)
        self.root.geometry(WINDOW_SIZE)
        
        # Set theme
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        
        # Initialize NVIDIA API client
        logging.info("Initializing NVIDIA API client")
        try:
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise ValueError("OPENAI_API_KEY not found in environment variables")
            
            logging.info(f"Using API key: {api_key[:10]}...")
            self.client = OpenAI(
                base_url="https://integrate.api.nvidia.com/v1",
                api_key=api_key
            )
            logging.info("NVIDIA API client initialized successfully")
        except Exception as e:
            logging.error(f"Failed to initialize NVIDIA API client: {str(e)}")
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
        # Configure root grid
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(0, weight=1)
        
        # Main content frame
        content_frame = ctk.CTkFrame(self.root, fg_color=DARK_BG)
        content_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=(10, 0))
        content_frame.grid_columnconfigure(0, weight=1)
        content_frame.grid_columnconfigure(1, weight=0)
        content_frame.grid_columnconfigure(2, weight=1)
        content_frame.grid_rowconfigure(0, weight=1)
        
        # Left Panel
        self.left_frame = ctk.CTkFrame(content_frame, fg_color=DARK_BG, width=CHAT_WIDTH)
        self.left_frame.grid(row=0, column=0, sticky="nsew")
        self.left_frame.grid_propagate(False)  # Maintain width
        self.left_frame.grid_columnconfigure(0, weight=1)
        self.left_frame.grid_rowconfigure(1, weight=1)  # Main content area
        
        # Chat Frame
        self.chat_frame = ChatFrame(self.left_frame)
        self.chat_frame.grid(row=1, column=0, sticky="nsew")
        
        # Code View
        self.code_view = CodeView(self.left_frame)
        self.code_view.configure(font=("Courier", FONT_SIZE))
        self.code_view.grid(row=1, column=0, sticky="nsew")
        self.code_view.grid_remove()
        
        # Resizable divider
        self.divider = ctk.CTkFrame(content_frame, width=5, fg_color="gray30")
        self.divider.grid(row=0, column=1, sticky="ns")
        self.divider.bind("<Enter>", lambda e: self.divider.configure(cursor="sb_h_double_arrow"))
        self.divider.bind("<Leave>", lambda e: self.divider.configure(cursor=""))
        self.divider.bind("<B1-Motion>", self.resize_panels)
        self.divider.bind("<Button-1>", self.start_resize)
        self.divider.bind("<ButtonRelease-1>", self.stop_resize)
        
        # Right Panel
        right_frame = ctk.CTkFrame(content_frame, fg_color=DARK_BG)
        right_frame.grid(row=0, column=2, sticky="nsew")
        right_frame.grid_columnconfigure(0, weight=1)
        right_frame.grid_rowconfigure(0, weight=1)
        
        # Canvas for diagram
        self.canvas = ctk.CTkCanvas(right_frame, bg="white", highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        
        # Bottom input area
        input_frame = ctk.CTkFrame(self.root, fg_color="#2B2B2B", corner_radius=15, height=50)
        input_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=10)
        input_frame.grid_columnconfigure(0, weight=1)  # Left spacing
        input_frame.grid_columnconfigure(1, weight=0)  # Toggle
        input_frame.grid_columnconfigure(2, weight=0)  # Loading
        input_frame.grid_columnconfigure(3, weight=0)  # Input
        input_frame.grid_columnconfigure(4, weight=0)  # Enter
        input_frame.grid_columnconfigure(5, weight=1)  # Right spacing
        input_frame.grid_propagate(False)
        
        # View toggle at left
        self.view_toggle = ctk.CTkSegmentedButton(
            input_frame,
            values=["Chat", "Code"],
            command=self.toggle_view,
            selected_color=USER_BUBBLE_COLOR,
            unselected_color="gray30",
            selected_hover_color=USER_BUBBLE_COLOR,
            unselected_hover_color="gray40",
            width=100,
            height=32,
            font=("Helvetica", FONT_SIZE-2),
            dynamic_resizing=False
        )
        self.view_toggle.grid(row=0, column=1, padx=10)
        self.view_toggle.set("Chat")
        
        # Loading indicator
        self.loading_indicator = LoadingIndicator(input_frame)
        self.loading_indicator.grid(row=0, column=2, padx=5)
        
        # Input field
        self.input_text = ctk.CTkEntry(
            input_frame,
            height=32,
            width=800,
            corner_radius=10,
            font=("Helvetica", FONT_SIZE),
            fg_color="#383B42",
            text_color="white",
            justify="left"  # Left-aligned text
        )
        self.input_text.grid(row=0, column=3, padx=5, pady=9)
        self.input_text.insert(0, "Describe the diagram you want to create...")
        
        # Enter button
        self.enter_button = ctk.CTkButton(
            input_frame,
            text="➜",
            width=32,
            height=32,
            corner_radius=16,
            fg_color=USER_BUBBLE_COLOR,
            hover_color="#1E3EAC",
            font=("Helvetica", FONT_SIZE),
            command=self.submit_input
        )
        self.enter_button.grid(row=0, column=4, padx=10)
        
        # Bind events
        self.input_text.bind("<FocusIn>", self.on_input_focus_in)
        self.input_text.bind("<FocusOut>", self.on_input_focus_out)
        self.input_text.bind("<Return>", self.submit_input)
        
        # Add welcome message
        self.chat_frame.add_message("Welcome! Describe the diagram you want to create.", is_user=False)
    
    def toggle_view(self, value=None):
        """Toggle between chat and code views"""
        if value is not None:
            self.show_chat = value == "Chat"
            self.view_toggle.set(value)
        else:
            self.show_chat = not self.show_chat
            self.view_toggle.set("Chat" if self.show_chat else "Code")
            
        if self.show_chat:
            self.code_view.grid_remove()
            self.chat_frame.grid(row=1, column=0, sticky="nsew")
            # Ensure latest messages are visible
            self.chat_frame.smooth_scroll_to_bottom()
        else:
            self.chat_frame.grid_remove()
            self.code_view.grid(row=1, column=0, sticky="nsew")
            if self.current_code:
                self.code_view.set_code(self.current_code)
    
    def start_resize(self, event):
        """Start panel resizing operation"""
        self.root.config(cursor="sb_h_double_arrow")
        self.start_x = event.x_root
        self.initial_width = self.left_frame.winfo_width()
    
    def stop_resize(self, event):
        """Stop panel resizing operation"""
        self.root.config(cursor="")
        
    def resize_panels(self, event):
        """Handle panel resizing"""
        if not hasattr(self, 'initial_width'):
            return
            
        # Calculate new width based on mouse position
        diff = event.x_root - self.start_x
        new_width = max(400, min(self.initial_width + diff, self.root.winfo_width() - 400))
        
        # Update immediately without waiting for next frame
        self.left_frame.configure(width=new_width)
        self.root.update_idletasks()

    def on_input_focus_in(self, event):
        if self.input_text.get() == "Describe the diagram you want to create...":
            self.input_text.delete(0, "end")
            self.input_text.configure(text_color="white")  # Reset to full opacity
    
    def on_input_focus_out(self, event):
        if not self.input_text.get().strip():
            self.input_text.delete(0, "end")
            self.input_text.insert(0, "Describe the diagram you want to create...")
            self.input_text.configure(text_color="gray70")  # Make placeholder text translucent
    
    def submit_input(self, event=None):
        """Handle input submission"""
        if self.loading_indicator.running:
            return
            
        text = self.input_text.get().strip()
        if not text or text == "Describe the diagram you want to create...":
            return
            
        self.chat_frame.add_message(text, is_user=True)
        self.input_text.delete(0, "end")
        self.input_text.insert(0, "")
        
        self.loading_indicator.start()
        self.process_input_async(text)
    
    def generate_diagram(self, user_input=None):
        """Generate TikZ diagram"""
        try:
            # Get input text
            if user_input is None:
                user_input = self.input_text.get().strip()
            if not user_input:
                return
            
            # Clear input
            self.input_text.delete(0, "end")
            self.loading_indicator.start()
            
            # Prepare messages for API
            messages = [
                {"role": "system", "content": TIKZ_SYSTEM_PROMPT},
                {"role": "user", "content": f"""
Please create a TikZ diagram based on this description: {user_input}

Important requirements:
1. Use ONLY RGB colors in format like 'rgb,255:red,173;green,216;blue,230' - DO NOT use named colors
2. Include all necessary TikZ libraries
3. Make the diagram clean and professional
4. Respond with a brief explanation followed by the code in a tikz code block
"""}
            ]
            
            # Make API call
            response = self.client.chat_completion(messages)
            
            # Process response
            self.process_response(response)
            
        except Exception as e:
            logging.error(f"Error generating diagram: {str(e)}")
            self.chat_frame.add_message(f"Error generating diagram: {str(e)}", is_user=False)
            self.loading_indicator.stop()
    
    async def generate_diagram_async(self, messages):
        """Generate TikZ diagram asynchronously using the NVIDIA API."""
        try:
            # Make API call
            response = await asyncio.to_thread(
                self.client.chat.completions.create,
                model="meta/llama-3.3-70b-instruct",
                messages=messages,
                temperature=0.01,
                top_p=0.7,
                max_tokens=1024
            )
            
            # Process in main thread
            self.root.after(0, lambda: self.process_response(response))
            
        except Exception as e:
            logging.error(f"Error generating diagram: {str(e)}")
            self.root.after(0, lambda: self.handle_error(str(e)))
        finally:
            self.root.after(100, self.check_results)

    def render_tikz(self, tikz_code):
        """Render TikZ code to PDF and convert to PNG"""
        try:
            # Create temp directory
            temp_dir = tempfile.mkdtemp()
            logging.debug(f"Created temp directory: {temp_dir}")
            
            # Extract the tikzpicture environment
            tikz_content = tikz_code
            if "\\begin{tikzpicture}" in tikz_code:
                start = tikz_code.find("\\begin{tikzpicture}")
                end = tikz_code.find("\\end{tikzpicture}") + len("\\end{tikzpicture}")
                tikz_content = tikz_code[start:end]
            
            # Create LaTeX document with proper color definitions
            latex_template = r"""\documentclass[tikz,border=10pt]{standalone}
\usepackage{tikz}
\usepackage[dvipsnames,svgnames,x11names]{xcolor}
\usetikzlibrary{automata,arrows,backgrounds,fit,positioning,shapes}

% Define custom colors
\definecolor{lightblue}{RGB}{173,216,230}
\definecolor{lightred}{RGB}{255,182,193}
\definecolor{lightgreen}{RGB}{144,238,144}
\definecolor{lightyellow}{RGB}{255,255,224}
\definecolor{lightgray}{RGB}{211,211,211}

\begin{document}
{content}
\end{document}
"""
            latex_code = latex_template.replace("{content}", tikz_content)
            
            tex_file = os.path.join(temp_dir, "diagram.tex")
            with open(tex_file, "w") as f:
                f.write(latex_code)
            logging.debug(f"Wrote LaTeX file: {tex_file}")
            
            # Run pdflatex
            logging.info("Running pdflatex")
            process = subprocess.run(
                ["pdflatex", "-interaction=nonstopmode", tex_file],
                cwd=temp_dir,
                capture_output=True,
                text=True
            )
            
            if process.returncode != 0:
                logging.error(f"pdflatex error: {process.stdout}")
                error_msg = process.stdout
                if "Undefined color" in error_msg:
                    error_msg = "Error: Invalid color name used in diagram. Please use standard color names or RGB values."
                elif "Illegal parameter" in error_msg:
                    error_msg = "Error: Invalid TikZ parameters. Please check your node and path specifications."
                raise Exception(error_msg)
            
            # Convert PDF to PNG
            pdf_file = os.path.join(temp_dir, "diagram.pdf")
            png_file = os.path.join(temp_dir, "diagram.png")
            
            dpi = 300
            pages = convert_from_path(pdf_file, dpi)
            pages[0].save(png_file, "PNG")
            
            # Load PNG into PhotoImage
            image = Image.open(png_file)
            photo = ImageTk.PhotoImage(image)
            
            # Clear canvas and display image
            self.canvas.delete("all")
            self.canvas.create_image(
                self.canvas.winfo_width() / 2,
                self.canvas.winfo_height() / 2,
                image=photo,
                anchor="center"
            )
            self.canvas.image = photo  # Keep reference
            
            # Clean up
            shutil.rmtree(temp_dir)
            return True
            
        except Exception as e:
            logging.error(f"Error in render_tikz: {str(e)}")
            self.chat_frame.add_message(f"Error rendering diagram: {str(e)}", is_user=False)
            return False

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
        if "error" in result:
            error_message = f"Error: {result['error']}"
            self.chat_frame.add_message(error_message, is_user=False)
            self.loading_indicator.stop()
            return

        try:
            tikz_code = result["tikz_code"]
            
            # Store and display the code
            self.current_code = tikz_code
            if not self.show_chat:
                self.code_view.set_code(tikz_code)
            
            # Show in chat if in chat view
            if self.show_chat:
                self.chat_frame.add_message(tikz_code, is_user=False)
            
            # Render TikZ code
            self.render_tikz_async(tikz_code)
            
        except Exception as e:
            logging.error(f"Error updating UI: {str(e)}")
            self.chat_frame.add_message(f"Error updating UI: {str(e)}", is_user=False)
        finally:
            # Stop loading indicator
            self.loading_indicator.stop()

    def check_results(self):
        try:
            while True:
                result = self.result_queue.get_nowait()
                self.update_ui_with_result(result)
        except queue.Empty:
            pass
        finally:
            self.root.after(100, self.check_results)

    def process_input_async(self, text):
        self.generate_diagram(text)

    def process_response(self, response):
        """Process the API response"""
        try:
            # Extract the assistant's response
            content = response.choices[0].message.content
            
            # Extract TikZ code from the response
            tikz_code = None
            if "```tikz" in content:
                start = content.find("```tikz") + 6
                end = content.find("```", start)
                tikz_code = content[start:end].strip()
            
            # Add only the text response to chat (excluding the code)
            text_response = content
            if tikz_code:
                # Get everything before the code block
                pre_code = content[:content.find("```tikz")].strip()
                # Get everything after the code block
                post_code = content[content.find("```", start) + 3:].strip()
                # Combine non-code parts
                text_response = f"{pre_code}\n\n{post_code}".strip()
            
            if text_response:
                self.chat_frame.add_message(text_response, is_user=False)
            
            # If we have TikZ code, try to render it
            if tikz_code:
                success = self.render_tikz(tikz_code)
                if success:
                    self.current_code = tikz_code
                
            self.loading_indicator.stop()
            
        except Exception as e:
            logging.error(f"Error processing response: {str(e)}")
            self.chat_frame.add_message("Error processing response", is_user=False)
            self.loading_indicator.stop()
    
    def mainloop(self):
        self.root.mainloop()

def main():
    app = TikZGUI()
    app.mainloop()

if __name__ == "__main__":
    main()
