class Ganymede < Formula
  desc "Discord communications and productivity gateway for Antigravity"
  homepage "https://github.com/digitalforgeca/ganymede"
  url "file:///Users/mcdoolz/dev/ganymede", using: :git, branch: "master"
  version "0.1.35"

  depends_on "python@3.11"

  def install
    # Inject the git hash into the module's __init__.py before installation
    git_hash = `git rev-parse --short HEAD`.chomp
    inreplace "src/ganymede/__init__.py", 
              /__git_hash__ = .*/, 
              "__git_hash__ = \"#{git_hash}\""

    # Create a virtual environment inside the Homebrew libexec directory
    system "python3.11", "-m", "venv", libexec

    # Ensure core package management tools are up-to-date
    system libexec/"bin/pip", "install", "-U", "pip", "setuptools", "wheel"

    # Install the package and all of its dependencies
    system libexec/"bin/pip", "install", "."

    # Copy the plugins directory so the daemon can auto-install them during validation
    (libexec/"plugins").install "plugins/chalice"

    # Symlink the generated executable into the Homebrew bin directory
    bin.install_symlink libexec/"bin/ganymede"
  end

  # Skip cleaning libexec to avoid dylib linkage errors with Python wheels (like watchfiles)
  skip_clean "libexec"

  def caveats
    <<~EOS
      Ganymede has been installed successfully.
      
      To start the gateway, run:
        ganymede
        
      The user configuration file will automatically be created on first run at:
        ~/.ganymede/config.yaml
        
      You can access the embedded dashboard at:
        http://localhost:8180
    EOS
  end

  test do
    system "#{bin}/ganymede", "--help"
  end
end
