# Security Policy

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| 0.1.x   | :white_check_mark: |
| < 0.1   | :x:                |

## Reporting a Vulnerability

We take security vulnerabilities seriously. If you discover a security vulnerability, please follow these steps:

1. **Do NOT open a public issue** for the vulnerability.
2. Email the maintainer at: 1443584939@qq.com
3. Include the following information:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if any)

## Response Timeline

- **Acknowledgment**: Within 48 hours
- **Initial Assessment**: Within 7 days
- **Fix Release**: Within 30 days (severity dependent)

## Disclosure Policy

- Vulnerabilities will be disclosed after a fix is released
- Credit will be given to the reporter (unless they prefer to remain anonymous)

## Security Best Practices

When using sqlseed:

- **Database credentials**: Never hardcode credentials in your code or config files
- **Environment variables**: Use environment variables for sensitive configuration
- **Connection strings**: Store database URLs in environment variables, not in version control
- **AI API keys**: Store API keys in environment variables, never in config files
