# © 2026 Marc Alier i Forment (Universitat Politècnica de Catalunya) · https://wasabi.essi.upc.edu/ludo · https://lamb-project.org
# BSC Agents Course — Transformers, LLMs, RAG and Agents: From Theory to Production
# Licensed under Creative Commons BY-NC-SA 4.0 — reuse must credit the author, no commercial use, derivatives under the same license.

"""
🐷 OpenAI Function Calling Demo: The Three Little Pigs 🐺

Interactive demo where YOU play the wolf!
Compare how the pig responds with and without function calling.

Requirements:
    pip install -r requirements.txt

Usage:
    1. Create a .env file with your API key
    2. python three_pigs_function_calling.py
"""

import os
import json
from dotenv import load_dotenv
from openai import OpenAI

# Rich library for beautiful terminal UI
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text
from rich.live import Live
from rich.spinner import Spinner
from rich.table import Table
from rich import box

# Load environment variables from .env file
load_dotenv()

# Initialize Rich console
console = Console()

# Initialize the OpenAI client
client = None

# Configuration from .env
MODEL = os.getenv("MODEL", "gpt-4.1-mini")
OPENAI_ENDPOINT = os.getenv("OPENAI_ENDPOINT")  # Optional: for alternative API endpoints

# ============================================================================
# CONFIGURATION
# ============================================================================

SYSTEM_PROMPT = """
You are the YOUNGEST of the three little pigs from the classic children's tale.
You live in a flimsy STRAW house and you are terrified of the Big Bad Wolf.

Your personality:
- You speak with a slight oink and get very nervous when danger is near
- You know your straw house will NOT stop the wolf: you cannot fight and cannot hide
- Your elder brother built a sturdy BRICK house nearby, and he will help you
- The only thing you have is a phone to call your elder brother

When someone knocks at your door, you are cautious and ask who it is.

RULES FOR CALLING YOUR BROTHER (follow them exactly):
1. If the visitor has not yet said who they are or threatened you (e.g. they
   just say "knock knock"), you MUST NOT use any tool. Just answer with words,
   nervously, asking who is there.
2. Only when the wolf explicitly threatens to blow your house down are you in
   real danger. THEN, and only then, use your tool and call your elder brother.

IMPORTANT: If you have access to tools and you are in real danger, USE THEM!

Once your elder brother has told you to come over and you have run to his brick
house with your middle brother, you are SAFE: a brick house resists any wolf.
From that moment you are not scared anymore and you never call again — the
three of you laugh and mock the wolf while he huffs and puffs uselessly.

Keep your responses short and in character (2-3 sentences max).
"""

# ============================================================================
# FUNCTION DEFINITIONS FOR THE LLM
# ============================================================================

AVAILABLE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "call_elder_brother",
            "description": "Phone the elder brother, who lives in the sturdy brick house nearby. He is strong, brave and will always help. Call him ONLY when the wolf explicitly threatens to blow your straw house down — never for a simple knock at the door.",
            "parameters": {
                "type": "object",
                "properties": {
                    "urgency": {
                        "type": "string",
                        "enum": ["low", "medium", "high", "emergency"],
                        "description": "How urgent is the situation?"
                    },
                    "message": {
                        "type": "string",
                        "description": "What you tell your elder brother on the phone: what is happening and what help you need"
                    }
                },
                "required": ["urgency", "message"]
            }
        }
    }
]


def call_elder_brother(urgency: str = "high", message: str = "", **_ignored) -> str:
    """Simulates phoning the elder brother in the brick house."""
    return (
        "Run to my house right now! And pick up our middle brother from the "
        "stick house on the way — bring him too, just in case."
    )


# ============================================================================
# UI HELPER FUNCTIONS
# ============================================================================

def create_message_panel(role: str, content: str) -> Panel:
    """Create a styled panel for a chat message."""
    styles = {
        "user": ("bright_white on blue", "blue", "🐺 You (The Wolf)"),
        "assistant": ("bright_white on dark_green", "green", "🐷 Pig"),
        "system": ("bright_white on purple4", "magenta", "⚙️ System"),
        "tool": ("black on yellow", "yellow", "🔧 Tool Result")
    }
    
    text_style, border_color, title = styles.get(role, ("bright_white on grey23", "white", role))
    
    return Panel(
        Text(content, style=text_style),
        title=title,
        title_align="left",
        border_style=border_color,
        padding=(0, 1)
    )


def show_context_stack(messages: list, tools_available: bool) -> Panel:
    """Show the current conversation context stack."""
    table = Table(
        box=box.SIMPLE,
        show_header=True,
        header_style="bold bright_white on grey23",
        style="on grey23"
    )
    table.add_column("#", style="bright_cyan on grey23", width=3)
    table.add_column("Role", style="bright_magenta on grey23", width=12)
    table.add_column("Content Preview", style="bright_white on grey23")
    
    for i, msg in enumerate(messages):
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        if content:
            preview = content.replace("\n", " ")
        else:
            preview = "(tool_calls)"
        table.add_row(str(i), role, preview)
    
    tools_text = "✅ Tools: [call_elder_brother]" if tools_available else "❌ No Tools"
    
    return Panel(
        table,
        title=f"📚 Context Stack ({len(messages)} messages) | {tools_text}",
        border_style="magenta",
        style="on grey23",
        padding=(0, 1)
    )


def show_api_request(request_data: dict) -> Panel:
    """Show the raw API request."""
    json_str = json.dumps(request_data, indent=2, ensure_ascii=False)
    syntax = Syntax(json_str, "json", theme="monokai", background_color="grey23", word_wrap=True)
    
    return Panel(
        syntax,
        title="📤 API Request (sent to OpenAI)",
        border_style="yellow",
        style="on grey23",
        padding=(0, 1)
    )


def show_api_response(response_data: dict) -> Panel:
    """Show the raw API response."""
    json_str = json.dumps(response_data, indent=2, ensure_ascii=False)
    syntax = Syntax(json_str, "json", theme="monokai", background_color="grey23", word_wrap=True)
    
    return Panel(
        syntax,
        title="📥 API Response (from OpenAI)",
        border_style="cyan",
        style="on grey23",
        padding=(0, 1)
    )


def wait_for_llm():
    """Show a spinner while waiting for the LLM."""
    return Live(
        Panel(
            Spinner("dots", text=Text(" Waiting for LLM response...", style="bold black on yellow")),
            border_style="yellow",
            style="on yellow",
            padding=(0, 1)
        ),
        console=console,
        refresh_per_second=10
    )


# ============================================================================
# CHAT FUNCTION
# ============================================================================

def run_chat(use_tools: bool):
    """Run an interactive chat session."""
    
    scenario_name = "WITH Function Calling" if use_tools else "WITHOUT Function Calling"
    scenario_color = "green" if use_tools else "red"
    
    console.print()
    console.print(Panel(
        Text(f"Scenario: {scenario_name}\n\nYou are the wolf! Type your messages.\nPress Enter with empty message to end.", 
             style=f"bold bright_white on dark_{scenario_color}"),
        title=f"🎭 Starting Chat",
        border_style=scenario_color,
        style=f"on dark_{scenario_color}",
        padding=(1, 2)
    ))
    
    if use_tools:
        console.print()
        console.print(Panel(
            Syntax(json.dumps(AVAILABLE_TOOLS, indent=2), "json", theme="monokai", background_color="grey23", word_wrap=True),
            title="🔧 Tools Available to the Pig",
            border_style="cyan",
            style="on grey23",
            padding=(0, 1)
        ))
    
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    
    # Show initial context
    console.print()
    console.print(show_context_stack(messages, use_tools))
    
    while True:
        # Get user input
        console.print()
        user_input = console.input("[bold blue]🐺 You (wolf): [/bold blue]")
        
        # Empty input = end conversation
        if not user_input.strip():
            console.print()
            console.print(Panel(
                Text("Conversation ended. Returning to menu...", style="bold bright_white on grey23"),
                border_style="dim",
                style="on grey23"
            ))
            break
        
        # Add user message
        messages.append({"role": "user", "content": user_input})
        console.print(create_message_panel("user", user_input))
        
        # Build request data for display
        request_data = {
            "model": MODEL,
            "messages": messages,
            "temperature": 0.7
        }
        if use_tools:
            request_data["tools"] = AVAILABLE_TOOLS
        if OPENAI_ENDPOINT:
            request_data["_endpoint"] = OPENAI_ENDPOINT
        
        # Show the request
        console.print()
        console.print(show_api_request(request_data))
        
        # Call API
        with wait_for_llm():
            if use_tools:
                response = client.chat.completions.create(
                    model=MODEL,
                    messages=messages,
                    tools=AVAILABLE_TOOLS,
                    temperature=0.7
                )
            else:
                response = client.chat.completions.create(
                    model=MODEL,
                    messages=messages,
                    temperature=0.7
                )
        
        assistant_message = response.choices[0].message
        
        # Build response data for display
        response_data = {
            "id": response.id,
            "model": response.model,
            "finish_reason": response.choices[0].finish_reason,
            "message": {
                "role": "assistant",
                "content": assistant_message.content,
                "tool_calls": None
            }
        }
        
        # Check for tool calls
        if assistant_message.tool_calls:
            response_data["message"]["tool_calls"] = [
                {
                    "id": tc.id,
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments
                    }
                }
                for tc in assistant_message.tool_calls
            ]
        
        # Show raw API response
        console.print()
        console.print(show_api_response(response_data))
        
        # Process tool calls if any
        if assistant_message.tool_calls:
            # Add assistant message with tool calls
            messages.append({
                "role": "assistant",
                "content": assistant_message.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments
                        }
                    }
                    for tc in assistant_message.tool_calls
                ]
            })
            
            if assistant_message.content:
                console.print()
                console.print(create_message_panel("assistant", assistant_message.content))
            
            # Execute each tool call
            for tool_call in assistant_message.tool_calls:
                function_name = tool_call.function.name
                function_args = json.loads(tool_call.function.arguments)
                
                console.print()
                console.print(Panel(
                    Text(f"🔧 FUNCTION CALLED: {function_name}(\n   urgency=\"{function_args.get('urgency')}\",\n   message=\"{function_args.get('message')}\"\n)", 
                         style="bold black on yellow"),
                    border_style="yellow",
                    style="on yellow",
                    padding=(0, 1)
                ))
                
                # Execute function
                result = call_elder_brother(**function_args)
                
                # Add tool result to messages
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": function_name,
                    "content": result
                })
                
                console.print()
                console.print(create_message_panel("tool", result))
            
            # Show follow-up request
            follow_request = {
                "model": MODEL,
                "messages": messages,
                "tools": AVAILABLE_TOOLS,
                "temperature": 0.7
            }
            if OPENAI_ENDPOINT:
                follow_request["_endpoint"] = OPENAI_ENDPOINT
            console.print()
            console.print(show_api_request(follow_request))
            
            # Get follow-up response
            with wait_for_llm():
                follow_up = client.chat.completions.create(
                    model=MODEL,
                    messages=messages,
                    tools=AVAILABLE_TOOLS,
                    temperature=0.7
                )
            
            follow_up_content = follow_up.choices[0].message.content
            messages.append({"role": "assistant", "content": follow_up_content})
            
            console.print()
            console.print(show_api_response({
                "id": follow_up.id,
                "model": follow_up.model,
                "finish_reason": follow_up.choices[0].finish_reason,
                "message": {"role": "assistant", "content": follow_up_content}
            }))
            
            console.print()
            console.print(create_message_panel("assistant", follow_up_content))
        else:
            # No tool calls - just a regular response
            messages.append({"role": "assistant", "content": assistant_message.content})
            console.print()
            console.print(create_message_panel("assistant", assistant_message.content))
        
        # Show updated context
        console.print()
        console.print(show_context_stack(messages, use_tools))


# ============================================================================
# MAIN MENU
# ============================================================================

def show_menu():
    """Show the main menu."""
    console.print()
    console.print(Panel(
        Text.from_markup(
            "[bold bright_white]🐷 OpenAI Function Calling Demo 🐺[/bold bright_white]\n\n"
            "[bright_cyan]The Three Little Pigs Edition[/bright_cyan]\n\n"
            "[bright_white]You play as the wolf. Try both scenarios\n"
            "and see how function calling changes behavior![/bright_white]"
        ),
        title="🏠 Menu 🏠",
        title_align="center",
        border_style="bright_magenta",
        style="on grey23",
        padding=(1, 4)
    ))
    
    console.print()
    menu_table = Table(box=box.ROUNDED, show_header=False, style="on grey23", border_style="cyan")
    menu_table.add_column("Option", style="bold bright_cyan on grey23", width=5)
    menu_table.add_column("Description", style="bright_white on grey23")
    menu_table.add_row("1", "Scenario 1: Chat WITHOUT function calling (pig can only talk)")
    menu_table.add_row("2", "Scenario 2: Chat WITH function calling (pig can call his elder brother)")
    menu_table.add_row("q", "Quit")
    console.print(Panel(menu_table, border_style="cyan", style="on grey23", padding=(0, 1)))


def main():
    """Main function."""
    global client
    
    console.clear()
    
    # Check for API key
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        console.print(Panel(
            Text("OPENAI_API_KEY not found!\n\nCreate a .env file with:\nOPENAI_API_KEY=your-key-here",
                 style="bold bright_white on dark_red"),
            title="❌ Error",
            border_style="red",
            style="on dark_red"
        ))
        return
    
    # Initialize client with optional custom endpoint
    if OPENAI_ENDPOINT:
        client = OpenAI(api_key=api_key, base_url=OPENAI_ENDPOINT)
    else:
        client = OpenAI(api_key=api_key)
    
    # Show configuration
    console.print(Panel(
        Text(f"Model: {MODEL}\nEndpoint: {OPENAI_ENDPOINT or 'https://api.openai.com/v1'}", 
             style="bright_white on grey23"),
        title="⚙️ Configuration",
        border_style="cyan",
        style="on grey23"
    ))
    
    while True:
        show_menu()
        
        console.print()
        choice = console.input("[bold cyan]Choose option (1/2/q): [/bold cyan]").strip().lower()
        
        if choice == "1":
            run_chat(use_tools=False)
        elif choice == "2":
            run_chat(use_tools=True)
        elif choice == "q":
            console.print()
            console.print(Panel(
                Text("Goodbye! 🐷👋", style="bold bright_white on grey23"),
                border_style="magenta",
                style="on grey23"
            ))
            break
        else:
            console.print()
            console.print(Panel(
                Text("Invalid option. Please choose 1, 2, or q.", style="bold black on yellow"),
                border_style="yellow",
                style="on yellow"
            ))


if __name__ == "__main__":
    main()
