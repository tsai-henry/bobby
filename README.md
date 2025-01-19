# Bobby

A modern GUI application that converts natural language descriptions into TikZ diagrams using NVIDIA's LLaMA API. Create beautiful mathematical diagrams, flowcharts, and technical illustrations with simple text descriptions.

## Features

- **Natural Language Generation**: Describe your diagram in plain English
- **Live Preview**: See your diagrams update in real-time
- **Code Editor**: Built-in TikZ code editor with syntax highlighting
- **Chat Interface**: User-friendly chat-like interface for diagram requests
- **Dark Theme**: Modern, eye-friendly dark interface

## Quick Start

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Install LaTeX (if not already installed):
   - macOS: `brew install texlive`
   - Ubuntu: `sudo apt-get install texlive-full`
   - Windows: Install MiKTeX from https://miktex.org/

3. Set up your API key:
   - Create a `.env` file in the project root
   - Add your NVIDIA API key: `OPENAI_API_KEY=your-api-key`

4. Run the application:
```bash
python tikz_gui.py
```

## Usage Examples

1. Create a simple flowchart:
```
Create a flowchart with three boxes labeled 'Start', 'Process', and 'End', connected by arrows
```

2. Draw a mathematical diagram:
```
Draw a right triangle with sides labeled 'a', 'b', and 'c', with a 90-degree angle marker
```

## Requirements

- Python 3.8+
- LaTeX distribution with TikZ package
- Required Python packages (see requirements.txt):
  - customtkinter==5.2.1
  - Pillow==10.1.0
  - pdf2image==1.16.3
  - openai==1.6.1
  - python-dotenv==1.0.0

## Development

The application is structured into a single file for simplicity:

- `tikz_gui.py`: Main application with UI components and TikZ rendering
- `.env`: Configuration file for API keys
- `requirements.txt`: Python package dependencies

## License

MIT License - Feel free to use and modify as needed.