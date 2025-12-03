from agents import parser_agent
from conf import types_def

res = parser_agent.run_sync("""
    Extract the requested information from the following text:
    
    "Physician P001, called John Doe, has a DO credential"
    
    Extract the information about the credential, which is one option among 'MD', 'DO', and 'MBBS'
""", output_type=types_def['credential']['def'])

print(res.output.value)