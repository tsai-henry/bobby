import tkinter as tk
from tkinter import ttk, messagebox

class MainApplication:
    def __init__(self, root):
        self.root = root
        self.root.title("My GUI Application")
        self.root.geometry("800x600")
        
        # Create main frame
        self.main_frame = ttk.Frame(self.root, padding="10")
        self.main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Create widgets
        self.create_widgets()
        
        # Configure grid weights
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        
    def create_widgets(self):
        # Example Label
        self.label = ttk.Label(self.main_frame, text="Welcome to My GUI App!")
        self.label.grid(row=0, column=0, pady=10)
        
        # Example Entry
        self.entry = ttk.Entry(self.main_frame)
        self.entry.grid(row=1, column=0, pady=5)
        
        # Example Button
        self.button = ttk.Button(self.main_frame, text="Click Me!", command=self.button_click)
        self.button.grid(row=2, column=0, pady=5)
        
        # Example Listbox
        self.listbox = tk.Listbox(self.main_frame, height=5)
        self.listbox.grid(row=3, column=0, pady=5)
        for item in ["Item 1", "Item 2", "Item 3"]:
            self.listbox.insert(tk.END, item)
            
    def button_click(self):
        text = self.entry.get()
        if text:
            messagebox.showinfo("Message", f"You entered: {text}")
        else:
            messagebox.showwarning("Warning", "Please enter some text!")

def main():
    root = tk.Tk()
    app = MainApplication(root)
    root.mainloop()

if __name__ == "__main__":
    main()
