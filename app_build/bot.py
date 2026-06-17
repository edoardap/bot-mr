#!/usr/bin/env python3
import os
import sys
import json
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
import discord
from discord.ext import tasks
import gitlab

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("gitlab_discord_bot")

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DISCORD_CHANNEL_ID = os.getenv("DISCORD_CHANNEL_ID")
GITLAB_TOKEN = os.getenv("GITLAB_TOKEN")
GITLAB_PROJECT_ID = os.getenv("GITLAB_PROJECT_ID")
GITLAB_GROUP_ID = os.getenv("GITLAB_GROUP_ID")
GITLAB_URL = os.getenv("GITLAB_URL", "https://gitlab.com")
SUMMARY_INTERVAL_HOURS = int(os.getenv("SUMMARY_INTERVAL_HOURS", "24"))
STALE_THRESHOLD_DAYS = int(os.getenv("STALE_THRESHOLD_DAYS", "3"))

# Mock Merge Request class for local verification/dry-run mode
class MockMergeRequest:
    def __init__(self, title, web_url, labels, author_username, assignees=None, reviewers=None, updated_days_ago=0, draft=False, work_in_progress=False):
        self.title = title
        self.web_url = web_url
        self.labels = labels
        self.author = {"username": author_username, "name": f"Name of {author_username}"}
        self.assignees = assignees or []
        self.reviewers = reviewers or []
        
        # Calculate updated_at
        now = datetime.now(timezone.utc)
        updated_dt = now - timedelta(days=updated_days_ago)
        self.updated_at = updated_dt.isoformat().replace("+00:00", "Z")
        
        self.draft = draft
        self.work_in_progress = work_in_progress

def get_mock_mrs():
    """Generates mock merge requests for dry-run/testing purposes."""
    return [
        MockMergeRequest(
            title="Feat: Implement login screen",
            web_url="https://gitlab.com/mock/project/-/merge_requests/1",
            labels=["Aguardando Revisão"],
            author_username="gitlab_user_1",
            assignees=[{"username": "gitlab_user_2"}],
            reviewers=[{"username": "gitlab_user_1"}]
        ),
        MockMergeRequest(
            title="Fix: Resolve DB connection pool leak",
            web_url="https://gitlab.com/mock/project/-/merge_requests/2",
            labels=["Alterações Solicitadas"],
            author_username="gitlab_user_1",
            assignees=[],
            reviewers=[]
        ),
        MockMergeRequest(
            title="Docs: Update API guide",
            web_url="https://gitlab.com/mock/project/-/merge_requests/3",
            labels=["Aguardando Revisão"],
            author_username="gitlab_user_2",
            assignees=[],
            reviewers=[]
        ),
        MockMergeRequest(
            title="Refactor: Core authentication logic",
            web_url="https://gitlab.com/mock/project/-/merge_requests/4",
            labels=["Aguardando Revisão"],
            author_username="gitlab_user_1",
            assignees=[{"username": "gitlab_user_2"}],
            reviewers=[],
            updated_days_ago=5 # Older than stale threshold (3 days)
        ),
        MockMergeRequest(
            title="WIP: Experimental performance test",
            web_url="https://gitlab.com/mock/project/-/merge_requests/5",
            labels=["wip"],
            author_username="gitlab_user_2",
            assignees=[],
            reviewers=[],
            draft=True
        )
    ]

def fetch_gitlab_data(gitlab_url, gitlab_token, project_id, stale_days, group_id=None, mock=False):
    """
    Connects to GitLab API and retrieves opened merge requests,
    or returns generated mock MR data if mock=True.
    """
    if mock:
        logger.info("Using mock GitLab data...")
        mrs = get_mock_mrs()
    else:
        logger.info(f"Connecting to GitLab instance at {gitlab_url}...")
        gl = gitlab.Gitlab(url=gitlab_url, private_token=gitlab_token)
        if group_id:
            logger.info(f"Fetching Merge Requests for GitLab group: {group_id}")
            group = gl.groups.get(group_id)
            mrs = group.mergerequests.list(state='opened', all=True)
        else:
            logger.info(f"Fetching Merge Requests for GitLab project: {project_id}")
            project = gl.projects.get(project_id)
            mrs = project.mergerequests.list(state='opened', all=True)

    awaiting_review = []
    changes_requested = []
    stale_mrs = []
    no_reviewers = []
    reviewer_workload = {}
    
    now = datetime.now(timezone.utc)
    
    for mr in mrs:
        # Check if draft or WIP
        # Direct attribute access can differ for mock vs python-gitlab, handles both safely
        is_draft = getattr(mr, 'draft', False) or getattr(mr, 'work_in_progress', False)
        if is_draft:
            continue
            
        labels = [l.lower() for l in mr.labels]
        author = mr.author['username']
        
        # Determine if stale
        try:
            # Parse datetime handling 'Z' suffix
            dt_str = mr.updated_at.replace("Z", "+00:00")
            updated_at = datetime.fromisoformat(dt_str)
            is_stale = (now - updated_at).days >= stale_days
        except Exception as e:
            logger.warning(f"Error parsing date {mr.updated_at}: {e}")
            is_stale = False
            
        if is_stale:
            stale_mrs.append(mr)
            
        # Check awaiting review
        if any(lbl in labels for lbl in ['aguardando revisão', 'aguardando revisao', 'awaiting review']):
            reviewers = getattr(mr, 'reviewers', [])
            assignees = getattr(mr, 'assignees', [])
            
            mr_reviewers = []
            if reviewers:
                mr_reviewers.extend([r['username'] for r in reviewers])
            if assignees:
                mr_reviewers.extend([a['username'] for a in assignees])
                
            # Deduplicate reviewer usernames
            mr_reviewers = list(set(mr_reviewers))
            # Remove the author from the reviewers list
            mr_reviewers = [r for r in mr_reviewers if r != author]
            
            if not mr_reviewers:
                no_reviewers.append(mr)
            else:
                awaiting_review.append((mr, mr_reviewers))
                # Update workload counts
                for r in mr_reviewers:
                    reviewer_workload[r] = reviewer_workload.get(r, 0) + 1
                    
        # Check changes requested
        if any(lbl in labels for lbl in ['alterações solicitadas', 'alteracoes solicitadas', 'changes requested']):
            changes_requested.append(mr)
            
    return {
        'awaiting_review': awaiting_review,
        'changes_requested': changes_requested,
        'stale_mrs': stale_mrs,
        'no_reviewers': no_reviewers,
        'reviewer_workload': reviewer_workload
    }

def get_mention(username, mapping):
    """Translates GitLab username to Discord mention if mapped, else returns bold username."""
    discord_id = mapping.get(username)
    if discord_id:
        return f"<@{discord_id}>"
    return f"**@{username}**"

def format_summary_embeds(data, mapping):
    """Formats the fetched data dictionary into a list of Discord Embed objects to handle long lists without truncation."""
    lines = []
    
    # 1. Aguardando Revisão
    awaiting = data['awaiting_review']
    lines.append("**📋 Aguardando Revisão**")
    if awaiting:
        for mr, reviewers in awaiting:
            rev_mentions = ", ".join([get_mention(r, mapping) for r in reviewers])
            lbl = "Revisor" if len(reviewers) == 1 else "Revisores"
            lines.append(f"• [{mr.title}]({mr.web_url}) - {lbl}: {rev_mentions}")
    else:
        lines.append("Nenhum MR aguardando revisão.")
    lines.append("") # spacer

    # 2. Alterações Solicitadas
    changes = data['changes_requested']
    lines.append("**🛠️ Alterações Solicitadas**")
    if changes:
        lines.append("*Ajustem seus MRs e façam rebase se necessário.*")
        for mr in changes:
            author_mention = get_mention(mr.author['username'], mapping)
            lines.append(f"• [{mr.title}]({mr.web_url}) - Autor: {author_mention}")
    else:
        lines.append("Nenhum MR com alterações solicitadas.")
    lines.append("") # spacer

    # 3. Sem Revisor Atribuído
    no_revs = data['no_reviewers']
    if no_revs:
        lines.append("**❓ Sem Revisor Atribuído**")
        for mr in no_revs:
            author_mention = get_mention(mr.author['username'], mapping)
            lines.append(f"• [{mr.title}]({mr.web_url}) (Autor: {author_mention})")
        lines.append("") # spacer

    # 4. Carga de Trabalho dos Revisores
    workload = data['reviewer_workload']
    lines.append("**⚖️ Carga de Trabalho dos Revisores**")
    if workload:
        for reviewer, count in sorted(workload.items(), key=lambda x: x[1], reverse=True):
            rev_mention = get_mention(reviewer, mapping)
            lines.append(f"• {rev_mention}: **{count}** MR(s)")
    else:
        lines.append("Nenhum revisor ativo atribuído.")
    lines.append("") # spacer

    # 5. MRs Parados (Inativos)
    stale = data['stale_mrs']
    if stale:
        lines.append("**⚠️ MRs Parados (Inativos)**")
        for mr in stale:
            author_mention = get_mention(mr.author['username'], mapping)
            last_date = mr.updated_at[:10] if mr.updated_at else "desconhecido"
            lines.append(f"• [{mr.title}]({mr.web_url}) - Última atualização: {last_date} (Autor: {author_mention})")
        lines.append("") # spacer

    # Now chunk the lines into embeds (max 4000 chars per embed description)
    embeds = []
    current_lines = ["Aqui está o detalhamento do status dos Merge Requests abertos:\n"]
    current_length = len(current_lines[0])

    for line in lines:
        line_len = len(line)
        # account for newline
        if current_length + line_len + 1 > 4000:
            embed = discord.Embed(
                title="🤖 Resumo de Merge Requests do GitLab",
                description="\n".join(current_lines),
                color=discord.Color.from_rgb(52, 152, 219),  # Premium blue
                timestamp=discord.utils.utcnow()
            )
            embed.set_footer(text="Bot de Resumo de MRs do GitLab")
            embeds.append(embed)
            
            # Start new embed
            current_lines = [line]
            current_length = line_len
        else:
            current_lines.append(line)
            current_length += line_len + 1

    if current_lines:
        embed = discord.Embed(
            title="🤖 Resumo de Merge Requests do GitLab",
            description="\n".join(current_lines),
            color=discord.Color.from_rgb(52, 152, 219),  # Premium blue
            timestamp=discord.utils.utcnow()
        )
        embed.set_footer(text="Bot de Resumo de MRs do GitLab")
        embeds.append(embed)

    return embeds


class MRBot(discord.Client):
    def __init__(self, mapping, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.mapping = mapping
        self.channel_id = int(DISCORD_CHANNEL_ID) if DISCORD_CHANNEL_ID else None
        self.use_mock = not (GITLAB_TOKEN and (GITLAB_PROJECT_ID or GITLAB_GROUP_ID))
        
    async def setup_hook(self) -> None:
        self.mr_summary_loop.start()
        logger.info("Background summary task loop started.")

    async def on_ready(self):
        logger.info(f"Logged in as {self.user.name} ({self.user.id})")
        # Start initial summary check on startup
        self.loop.create_task(self.post_initial_summary())

    async def post_initial_summary(self):
        await self.wait_until_ready()
        logger.info("Executing initial summary post on startup...")
        await self.send_mr_summary()

    @tasks.loop(hours=SUMMARY_INTERVAL_HOURS)
    async def mr_summary_loop(self):
        # Skip the first iteration execution of loop since we manually call post_initial_summary
        if self.mr_summary_loop.current_loop == 0:
            return
        logger.info("Executing scheduled summary post...")
        await self.send_mr_summary()

    @mr_summary_loop.before_loop
    async def before_mr_summary_loop(self):
        await self.wait_until_ready()

    async def send_mr_summary(self):
        if not self.channel_id:
            logger.error("DISCORD_CHANNEL_ID is not configured. Cannot post summary.")
            return
            
        channel = self.get_channel(self.channel_id)
        if not channel:
            try:
                channel = await self.fetch_channel(self.channel_id)
            except Exception as e:
                logger.error(f"Failed to fetch channel {self.channel_id}: {e}")
                return
                
        if not channel:
            logger.error(f"Channel with ID {self.channel_id} not found.")
            return

        try:
            # Execute GitLab API call in executor to avoid blocking the Discord bot client loop
            data = await asyncio.to_thread(
                fetch_gitlab_data,
                GITLAB_URL,
                GITLAB_TOKEN,
                GITLAB_PROJECT_ID,
                STALE_THRESHOLD_DAYS,
                GITLAB_GROUP_ID,
                self.use_mock
            )
        except Exception as e:
            logger.error(f"Failed to fetch GitLab data: {e}")
            embed = discord.Embed(
                title="❌ GitLab MR Fetch Error",
                description=f"An error occurred while fetching merge requests from GitLab:\n`{e}`",
                color=discord.Color.red(),
                timestamp=discord.utils.utcnow()
            )
            await channel.send(embed=embed)
            return

        embeds = format_summary_embeds(data, self.mapping)
        for embed in embeds:
            await channel.send(embed=embed)
        logger.info("Summary posted successfully to Discord channel.")

def run_dry_run(mapping):
    """Executes a dry-run local mock generation and outputs the formatted summary to console."""
    logger.info("Starting Dry-Run Mode...")
    data = fetch_gitlab_data(None, None, None, STALE_THRESHOLD_DAYS, None, mock=True)
    
    # Print a textual representation of the embed
    print("\n" + "="*50)
    print("REPRESENTAÇÃO MOCK DO EMBED DO DISCORD (DRY-RUN)")
    print("="*50)
    print("Título: Resumo de Merge Requests do GitLab")
    print("Descrição: Aqui está o detalhamento do status dos Merge Requests abertos:")
    print("-" * 50)
    
    # Awaiting Review
    print("📋 Aguardando Revisão:")
    for mr, reviewers in data['awaiting_review']:
        rev_mentions = ", ".join([get_mention(r, mapping) for r in reviewers])
        lbl = "Revisor" if len(reviewers) == 1 else "Revisores"
        print(f"  • {mr.title} ({mr.web_url}) - {lbl}: {rev_mentions}")
        
    # Changes Requested
    print("\n🛠️ Alterações Solicitadas:")
    print("  *Ajustem seus MRs e façam rebase se necessário.*")
    for mr in data['changes_requested']:
        author_mention = get_mention(mr.author['username'], mapping)
        print(f"  • {mr.title} ({mr.web_url}) - Autor: {author_mention}")
        
    # Needs Reviewer Assignment
    if data['no_reviewers']:
        print("\n❓ Sem Revisor Atribuído:")
        for mr in data['no_reviewers']:
            author_mention = get_mention(mr.author['username'], mapping)
            print(f"  • {mr.title} ({mr.web_url}) - Autor: {author_mention}")
            
    # Workloads
    print("\n⚖️ Carga de Trabalho dos Revisores:")
    for reviewer, count in sorted(data['reviewer_workload'].items(), key=lambda x: x[1], reverse=True):
        rev_mention = get_mention(reviewer, mapping)
        print(f"  • {rev_mention}: {count} MR(s)")
        
    # Stale
    if data['stale_mrs']:
        print("\n⚠️ MRs Parados (Inativos):")
        for mr in data['stale_mrs']:
            author_mention = get_mention(mr.author['username'], mapping)
            print(f"  • {mr.title} ({mr.web_url}) - Última Atualização: {mr.updated_at[:10]} - Autor: {author_mention}")
            
    print("="*50 + "\n")

def main():
    # Load mapping configuration
    mapping = {}
    mapping_path = os.path.join(os.path.dirname(__file__), "mapping.json")
    if os.path.exists(mapping_path):
        try:
            with open(mapping_path, "r") as f:
                mapping = json.load(f)
            logger.info(f"Loaded {len(mapping)} user mappings.")
        except Exception as e:
            logger.error(f"Could not load mapping.json: {e}")

    # Check for dry-run CLI argument
    if "--dry-run" in sys.argv:
        run_dry_run(mapping)
        return

    # Check for required configuration to run live
    if not DISCORD_TOKEN:
        logger.error("DISCORD_TOKEN environment variable not set. Running in dry-run mode automatically.")
        run_dry_run(mapping)
        return

    if not DISCORD_CHANNEL_ID:
        logger.error("DISCORD_CHANNEL_ID environment variable not set. Cannot run bot.")
        sys.exit(1)

    # Initialize intents and client
    intents = discord.Intents.default()
    client = MRBot(mapping=mapping, intents=intents)
    
    try:
        client.run(DISCORD_TOKEN)
    except Exception as e:
        logger.error(f"Error running Discord bot: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
