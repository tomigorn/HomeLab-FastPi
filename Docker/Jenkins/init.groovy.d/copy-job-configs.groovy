import jenkins.model.*
import groovy.io.FileType

def instance = Jenkins.getInstance()
def jenkinsRoot = instance.root
def src = new File(jenkinsRoot, 'casc_configs/jobs')
def dst = new File(jenkinsRoot, 'jobs')

if (src.exists()) {
  src.eachDir { jobDir ->
    def jobName = jobDir.name
    def jobDst = new File(dst, jobName)
    if (!jobDst.exists()) {
      jobDst.mkdirs()
      def srcConfig = new File(jobDir, 'config.xml')
      if (srcConfig.exists()) {
        srcConfig.withInputStream { is ->
          new File(jobDst, 'config.xml').withOutputStream { os -> os << is }
        }
        println("Installed job '${jobName}' from casc_configs/jobs/${jobName}")
      } else {
        println("No config.xml for ${jobName}, skipping")
      }
    } else {
      println("Job ${jobName} already exists, skipping install")
    }
  }
} else {
  println('No casc_configs/jobs directory found, skipping job install')
}
