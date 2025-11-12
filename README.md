# Automated Email Response System (n8n + Local AI Integration)

Automated email response system using n8n workflows, local Ollama AI, and Microsoft Outlook 365 integration.

## Quick Start

1. **Start services:**
   ```bash
   docker-compose up -d
   ```

2. **Pull Ollama model:**
   ```bash
   docker exec -it ollama_local ollama pull mistral
   ```

3. **Access n8n:**
   - http://localhost:5678
   - Login: admin / admin123

4. **Configure Outlook 365:**
   - Register app in Azure Portal
   - Add OAuth credentials in n8n

## Project Structure

```
├── docker-compose.yml    # Docker services
├── n8n_data/            # n8n persistent data
└── ollama/              # Ollama models
```
