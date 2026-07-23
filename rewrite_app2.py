import re

# Update main.tsx to use BrowserRouter
with open("src/ganymede/web/themes/default/src/main.tsx", "w") as f:
    f.write("""import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.tsx'
import { ChakraProvider } from '@chakra-ui/react'
import { BrowserRouter } from 'react-router-dom'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ChakraProvider>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </ChakraProvider>
  </React.StrictMode>,
)
""")

# Rewrite App.tsx to use Routes, Route, useNavigate, useLocation
with open("src/ganymede/web/themes/default/src/App.tsx", "r") as f:
    content = f.read()

# Replace react-icons/pi imports just in case
content = content.replace("from 'lucide-react';", "from 'react-icons/pi';")

content = content.replace("import { useEffect, useState, useRef } from 'react';", "import { useEffect, useState, useRef } from 'react';\nimport { Routes, Route, useNavigate, useLocation } from 'react-router-dom';")

# Remove activeView state and use useLocation / useNavigate
content = content.replace("const [activeView, setActiveView] = useState('dashboard');", """const navigate = useNavigate();
  const location = useLocation();
  const activeView = location.pathname === '/' ? 'dashboard' : location.pathname.substring(1);""")

content = content.replace("onClick={() => setActiveView('dashboard')}", "onClick={() => navigate('/')}")
content = content.replace("onClick={() => setActiveView('projects')}", "onClick={() => navigate('/projects')}")
content = content.replace("onClick={() => setActiveView('bots')}", "onClick={() => navigate('/bots')}")
content = content.replace("onClick={() => setActiveView('settings')}", "onClick={() => navigate('/settings')}")

# Update fetch logic
old_fetch_bots = "fetch('/api/bots').then(res => res.json()).then(data => { if (data) setStatus((prev: any) => ({ ...prev, bot_info: data })); }).catch(err => console.error(err));"
new_fetch_bots = "fetch('/api/bots').then(res => res.json()).then(data => { if (data && data.bots) setBotsList(data.bots); }).catch(err => console.error(err));"
content = content.replace(old_fetch_bots, new_fetch_bots)

# Add botsList state
content = content.replace("const [selectedChat, setSelectedChat] = useState<any>(null);", "const [selectedChat, setSelectedChat] = useState<any>(null);\n  const [botsList, setBotsList] = useState<any>({});")

# Also update the WS to handle botsList
ws_bots = "} else if (data.type === 'bots') {\n          setStatus((prev: any) => ({ ...prev, bot_info: data.payload }));"
new_ws_bots = "} else if (data.type === 'bots') {\n          setBotsList(data.payload);"
content = content.replace(ws_bots, new_ws_bots)


# Replace the content area with Routes
# We can just change `{activeView === 'dashboard' && (` to `<Routes><Route path="/" element={`
# Actually, the activeView checks are clean enough, but since we're using React Router, we should use Routes.
# Let's do it simply by wrapping the conditionals in <Routes> and <Route>s.

# Or since we defined `activeView` from `location.pathname`, we can keep `{activeView === 'dashboard' && ...}` for now, it achieves the exact same thing without re-indenting everything!
# Wait, let's use actual Routes for a standard approach.
import re

content = content.replace("{activeView === 'dashboard' && (", "<Routes>\n            <Route path=\"/\" element={<>")
content = content.replace("{activeView === 'projects' && (", "<Route path=\"/projects\" element={<>")
content = content.replace("{activeView === 'bots' && (", "<Route path=\"/bots\" element={<>")
content = content.replace("{activeView === 'settings' && (", "<Route path=\"/settings\" element={<>")

# We have to replace the closing `)}` with `</>} />` for each.
content = re.sub(r'(\s*)\)\}\s*(?=\{activeView === \'projects\'|<Route path="/projects")', r'\1</>} />\n\1', content)
content = re.sub(r'(\s*)\)\}\s*(?=\{activeView === \'bots\'|<Route path="/bots")', r'\1</>} />\n\1', content)
content = re.sub(r'(\s*)\)\}\s*(?=\{activeView === \'settings\'|<Route path="/settings")', r'\1</>} />\n\1', content)
content = re.sub(r'(\s*)\)\}\s*</Box>\s*</Flex>', r'\1</>} />\n          </Routes>\n\1</Box>\n      </Flex>', content)


# Now fix the Bots render
old_bots_render = """{status?.bot_info ? (
                <Box 
                  border="1px solid" borderColor="gray.200" borderRadius="md" p={4} 
                  display="flex" alignItems="center" justifyContent="space-between"
                  _hover={{ bg: "gray.50", shadow: "md", borderColor: "blue.300" }} 
                  cursor="pointer" transition="all 0.2s"
                  onClick={() => alert(`Configuring bot: ${status.bot_info.name}`)}
                >
                  <HStack spacing={4}>
                    <Box w="50px" h="50px" bg="gray.200" borderRadius="full" overflow="hidden">
                      {status.bot_info.avatar_url ? <img src={status.bot_info.avatar_url} alt="avatar" width="100%" height="100%" /> : <Flex w="100%" h="100%" align="center" justify="center"><PiRobot size={24} color="gray" /></Flex>}
                    </Box>
                    <Box>
                      <Text fontWeight="bold" fontSize="lg">{status.bot_info.name || "Ganymede"}</Text>
                      <Text fontSize="sm" color="gray.500">ID: {status.bot_info.id || "--"}</Text>
                    </Box>
                  </HStack>
                  <Button size="sm" colorScheme="blue" variant="outline" leftIcon={<PiGear size={16} />}>Configure</Button>
                </Box>
              ) : (
                <Text color="gray.500">No active bot connected.</Text>
              )}"""

new_bots_render = """{Object.keys(botsList).length > 0 ? (
                <VStack align="stretch" spacing={4}>
                  {Object.entries(botsList).map(([botId, bot]: [string, any]) => (
                    <Box 
                      key={botId}
                      border="1px solid" borderColor="gray.200" borderRadius="md" p={4} 
                      display="flex" alignItems="center" justifyContent="space-between"
                      _hover={{ bg: "gray.50", shadow: "md", borderColor: "blue.300" }} 
                      cursor="pointer" transition="all 0.2s"
                      onClick={() => alert(`Configuring bot: ${bot.name || botId}`)}
                    >
                      <HStack spacing={4}>
                        <Box w="50px" h="50px" bg="gray.200" borderRadius="full" overflow="hidden">
                          {bot.avatar_url ? <img src={bot.avatar_url} alt="avatar" width="100%" height="100%" /> : <Flex w="100%" h="100%" align="center" justify="center"><PiRobot size={24} color="gray" /></Flex>}
                        </Box>
                        <Box>
                          <Text fontWeight="bold" fontSize="lg">{bot.name || "Ganymede Bot"}</Text>
                          <Text fontSize="sm" color="gray.500">ID: {botId}</Text>
                        </Box>
                      </HStack>
                      <Button size="sm" colorScheme="blue" variant="outline" leftIcon={<PiGear size={16} />}>Configure</Button>
                    </Box>
                  ))}
                </VStack>
              ) : (
                <Text color="gray.500">No active bot connected.</Text>
              )}"""

content = content.replace(old_bots_render, new_bots_render)

with open("src/ganymede/web/themes/default/src/App.tsx", "w") as f:
    f.write(content)

