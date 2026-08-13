package main
import "os/exec"
func main() {
    cmd := exec.Command("sh", "-c", "python3 print_chain.py > go_chain.txt")
    cmd.Run()
}
