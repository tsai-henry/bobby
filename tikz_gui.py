import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import os
from dotenv import load_dotenv
from openai import OpenAI
import tempfile
import subprocess
from PIL import Image, ImageTk
import shutil
from pdf2image import convert_from_path

class TikZGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("TikZ Diagram Generator")
        self.root.geometry("1200x800")
        
        # Initialize NVIDIA API client
        self.client = OpenAI(
            base_url="https://integrate.api.nvidia.com/v1",
            api_key="***REMOVED***"
        )
        
        # Create main container
        self.create_gui_elements()
        
        # Configure grid weights
        self.root.columnconfigure(0, weight=1)
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)
        
    def create_gui_elements(self):
        # Left Panel (Chat Interface)
        left_frame = ttk.Frame(self.root, padding="10")
        left_frame.grid(row=0, column=0, sticky="nsew")
        
        # Chat history
        self.chat_history = scrolledtext.ScrolledText(left_frame, wrap=tk.WORD, height=30)
        self.chat_history.grid(row=0, column=0, sticky="nsew", pady=(0, 10))
        self.chat_history.insert(tk.END, "Welcome! Describe the diagram you want to create.\n\n")
        
        # Input area
        self.input_text = scrolledtext.ScrolledText(left_frame, wrap=tk.WORD, height=5)
        self.input_text.grid(row=1, column=0, sticky="ew", pady=(0, 5))
        
        # Send button
        send_button = ttk.Button(left_frame, text="Generate Diagram", command=self.generate_diagram)
        send_button.grid(row=2, column=0, sticky="e")
        
        # Configure left frame grid
        left_frame.columnconfigure(0, weight=1)
        left_frame.rowconfigure(0, weight=1)
        
        # Right Panel (Diagram Display)
        right_frame = ttk.Frame(self.root, padding="10")
        right_frame.grid(row=0, column=1, sticky="nsew")
        
        # Canvas for diagram display
        self.canvas = tk.Canvas(right_frame, bg="white")
        self.canvas.grid(row=0, column=0, sticky="nsew")
        
        # Configure right frame grid
        right_frame.columnconfigure(0, weight=1)
        right_frame.rowconfigure(0, weight=1)
        
    def generate_diagram(self):
        user_input = self.input_text.get("1.0", tk.END).strip()
        if not user_input:
            messagebox.showwarning("Warning", "Please enter a description for the diagram.")
            return
            
        self.chat_history.insert(tk.END, f"You: {user_input}\n\n")
        
        try:
            # Get TikZ code from NVIDIA API
            completion = self.client.chat.completions.create(
                model="meta/llama-3.3-70b-instruct",
                messages=[
                    {"role": "system", "content": "You are a helpful assistant that generates TikZ diagram code. Respond only with the complete LaTeX/TikZ code, including necessary preamble and document structure. Use the standalone document class."},
                    {"role": "user", "content": user_input}
                ],
                temperature=0.2,
                top_p=0.7,
                max_tokens=512,
                stream=True
            )
            
            # Handle streaming response
            tikz_code = ""
            self.chat_history.insert(tk.END, "Assistant: Here's your TikZ diagram code:\n")
            for chunk in completion:
                if chunk.choices[0].delta.content is not None:
                    content = chunk.choices[0].delta.content
                    tikz_code += content
                    self.chat_history.insert(tk.END, content)
                    self.chat_history.see(tk.END)
                    self.root.update()
            
            self.chat_history.insert(tk.END, "\n\n")
            
            # Render TikZ code
            self.render_tikz(tikz_code)
            
        except Exception as e:
            messagebox.showerror("Error", f"An error occurred: {str(e)}")
            
        self.input_text.delete("1.0", tk.END)
        self.chat_history.see(tk.END)
        
    def render_tikz(self, tikz_code):
        try:
            # Create a temporary directory for our files
            with tempfile.TemporaryDirectory() as tmpdir:
                # Write LaTeX code to temporary file
                tex_file = os.path.join(tmpdir, "diagram.tex")
                with open(tex_file, "w") as f:
                    f.write(tikz_code)
                
                # Compile LaTeX to PDF
                process = subprocess.run(
                    ["pdflatex", "-interaction=nonstopmode", "diagram.tex"],
                    cwd=tmpdir,
                    capture_output=True,
                    text=True
                )
                
                if process.returncode != 0:
                    raise Exception(f"LaTeX compilation failed:\n{process.stderr}")
                
                # Convert PDF to image using pdf2image
                pdf_file = os.path.join(tmpdir, "diagram.pdf")
                images = convert_from_path(pdf_file)
                if not images:
                    raise Exception("Failed to convert PDF to image")
                
                image = images[0]  # Get first page
                
                # Calculate scaling to fit the canvas while maintaining aspect ratio
                canvas_width = self.canvas.winfo_width()
                canvas_height = self.canvas.winfo_height()
                img_width, img_height = image.size
                
                scale = min(canvas_width/img_width, canvas_height/img_height)
                new_width = int(img_width * scale)
                new_height = int(img_height * scale)
                
                image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
                self.photo = ImageTk.PhotoImage(image)
                
                # Clear previous content and display new image
                self.canvas.delete("all")
                self.canvas.create_image(
                    canvas_width//2,
                    canvas_height//2,
                    image=self.photo,
                    anchor="center"
                )
                
        except Exception as e:
            messagebox.showerror("Error", f"Failed to render diagram: {str(e)}")

def main():
    root = tk.Tk()
    app = TikZGUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()
