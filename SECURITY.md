# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 1.0.x   | :white_check_mark: |

## Security Model & Sandbox Guarantees

Cyber Minecraft AI treats all incoming natural language prompts, AI outputs, and uploaded assets as untrusted:
- **No Arbitrary Shell Execution**: Build commands are strictly hardcoded and isolated.
- **Path Traversal Guards**: All user and project files are verified within the base directory root.
- **Zip Slip & Bomb Protection**: Archive extraction enforces size, file count, and destination checks.
- **Secret Redaction**: Structured logging filters out tokens from Telegram, Hugging Face, and external APIs.

## Reporting a Vulnerability

If you discover a security vulnerability in this project:
1. Please do **NOT** disclose the vulnerability publicly in an issue.
2. Email details to the repository maintainer or open a private security advisory on GitHub.
3. Include clear steps to reproduce and proof-of-concept if possible.
