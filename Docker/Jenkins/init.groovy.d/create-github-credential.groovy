import jenkins.model.*
import com.cloudbees.plugins.credentials.*
import com.cloudbees.plugins.credentials.domains.*
import org.jenkinsci.plugins.plaincredentials.impl.StringCredentialsImpl
import hudson.util.Secret

def env = System.getenv()
def credId = env['GITHUB_CREDENTIAL_ID'] ?: 'github-token'
def tokenFile = env['GITHUB_TOKEN_FILE'] ?: '/run/secrets/github_token'

println("Looking for GitHub token file at: ${tokenFile}")
def f = new File(tokenFile)
if (!f.exists()) {
  println("GitHub token file not found, skipping credential creation")
  return
}

def token = f.text.trim()
if (!token) {
  println("GitHub token file is empty, skipping credential creation")
  return
}

def store = SystemCredentialsProvider.getInstance().getStore()
def domain = Domain.global()

// Check if credential with same id exists
def existing = com.cloudbees.plugins.credentials.CredentialsProvider.lookupCredentials(
  com.cloudbees.plugins.credentials.common.StandardCredentials.class,
  Jenkins.instance,
  null,
  null
).find { it.id == credId }

if (existing) {
  println("Credential with id '${credId}' already exists, skipping creation")
  return
}

def secret = Secret.fromString(token)
def creds = new StringCredentialsImpl(CredentialsScope.GLOBAL, credId, "GitHub token (from file)", secret)
store.addCredentials(domain, creds)
println("Created GitHub credential with id: ${credId}")
