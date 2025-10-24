import jenkins.model.*
import hudson.security.*

def instance = Jenkins.getInstance()
def env = System.getenv()
def adminUser = env['JENKINS_ADMIN_ID'] ?: 'admin'
def adminPass = env['JENKINS_ADMIN_PASSWORD'] ?: 'admin'

println("--> creating admin user: ${adminUser}")
def hudsonRealm = new HudsonPrivateSecurityRealm(false)
hudsonRealm.createAccount(adminUser, adminPass)
instance.setSecurityRealm(hudsonRealm)

def strategy = new FullControlOnceLoggedInAuthorizationStrategy()
strategy.setAllowAnonymousRead(false)
instance.setAuthorizationStrategy(strategy)

instance.save()
