import re

with open("src/ganymede/web/themes/default/src/App.tsx", "r") as f:
    content = f.read()

# Let's see if there is any interval or if they just mean to use the WebSocket payload for chats/status.
content = content.replace("import { useEffect, useState, useRef } from 'react';", "import { useEffect, useState, useRef } from 'react';\nimport { Bot, Settings, LayoutDashboard, Folder, Download, Search, MessageSquare, Play, Square, Activity, Server, Hash } from 'lucide-react';")

# 1. Update the sidebar buttons with icons
content = content.replace(
    "<Button w=\"100%\" justifyContent=\"flex-start\" variant={activeView === 'dashboard' ? 'solid' : 'ghost'} colorScheme=\"blue\" onClick={() => setActiveView('dashboard')}>Dashboard</Button>",
    "<Button w=\"100%\" justifyContent=\"flex-start\" leftIcon={<LayoutDashboard size={18} />} variant={activeView === 'dashboard' ? 'solid' : 'ghost'} colorScheme=\"blue\" onClick={() => setActiveView('dashboard')}>Dashboard</Button>"
)
content = content.replace(
    "<Button w=\"100%\" justifyContent=\"flex-start\" variant={activeView === 'projects' ? 'solid' : 'ghost'} colorScheme=\"blue\" onClick={() => setActiveView('projects')}>Projects</Button>",
    "<Button w=\"100%\" justifyContent=\"flex-start\" leftIcon={<Folder size={18} />} variant={activeView === 'projects' ? 'solid' : 'ghost'} colorScheme=\"blue\" onClick={() => setActiveView('projects')}>Projects</Button>"
)
content = content.replace(
    "<Button w=\"100%\" justifyContent=\"flex-start\" variant={activeView === 'bots' ? 'solid' : 'ghost'} colorScheme=\"blue\" onClick={() => setActiveView('bots')}>Bots</Button>",
    "<Button w=\"100%\" justifyContent=\"flex-start\" leftIcon={<Bot size={18} />} variant={activeView === 'bots' ? 'solid' : 'ghost'} colorScheme=\"blue\" onClick={() => setActiveView('bots')}>Bots</Button>"
)
content = content.replace(
    "<Button w=\"100%\" justifyContent=\"flex-start\" variant={activeView === 'settings' ? 'solid' : 'ghost'} colorScheme=\"blue\" onClick={() => setActiveView('settings')}>Settings</Button>",
    "<Button w=\"100%\" justifyContent=\"flex-start\" leftIcon={<Settings size={18} />} variant={activeView === 'settings' ? 'solid' : 'ghost'} colorScheme=\"blue\" onClick={() => setActiveView('settings')}>Settings</Button>"
)

# Replace the fetching on mount with just websocket driven.
# Wait, they might still need initial fetch, but the prompt says: "We don't want to do this sort of cyclical hit; we want event driven processes."
# I will use WS for everything.
old_use_effect = """  useEffect(() => {
    fetch('/api/status')
      .then(res => res.json())
      .then(data => setStatus(data))
      .catch(err => console.error("Status fetch failed", err));

    fetch('/api/chats')
      .then(res => res.json())
      .then(data => {
        if (data && data.chats) {
          setChats(data.chats);
        }
      })
      .catch(err => console.error("Chats fetch failed", err));

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/dashboard`;
    const ws = new WebSocket(wsUrl);

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        setLogs(prev => [...prev, data]);
      } catch (e) {
        setLogs(prev => [...prev, { event: event.data, level: 'info' }]);
      }
    };

    return () => {
      ws.close();
    };
  }, []);"""

new_use_effect = """  useEffect(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/dashboard`;
    const ws = new WebSocket(wsUrl);

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === 'status') {
          setStatus(data.payload);
        } else if (data.type === 'chats') {
          setChats(data.payload || []);
        } else if (data.type === 'bots') {
          setStatus((prev: any) => ({ ...prev, bot_info: data.payload }));
        } else if (data.chats) {
          setChats(data.chats);
        } else if (data.status) {
          setStatus(data);
        } else {
          setLogs(prev => [...prev, data]);
        }
      } catch (e) {
        setLogs(prev => [...prev, { event: event.data, level: 'info' }]);
      }
    };
    
    // Initial fetch to get initial state before WS events come in
    fetch('/api/status').then(res => res.json()).then(data => setStatus(data)).catch(err => console.error(err));
    fetch('/api/chats').then(res => res.json()).then(data => { if (data && data.chats) setChats(data.chats); }).catch(err => console.error(err));
    fetch('/api/bots').then(res => res.json()).then(data => { if (data) setStatus((prev: any) => ({ ...prev, bot_info: data })); }).catch(err => console.error(err));

    return () => ws.close();
  }, []);"""

content = content.replace(old_use_effect, new_use_effect)


# For the per chat header:
# Let's find:
# <Box flex={1} bg="gray.50" borderRadius="md" display="flex" alignItems="center" justifyContent="center" p={4}>
# <Text color="gray.500" m="auto">Select a project to view chat</Text>
# </Box>

old_chat_area = """<Box flex={1} bg="gray.50" borderRadius="md" display="flex" alignItems="center" justifyContent="center" p={4}>
                    <Text color="gray.500" m="auto">Select a project to view chat</Text>
                  </Box>"""

new_chat_area = """{selectedChat ? (
                    <Box flex={1} bg="white" borderRadius="md" display="flex" flexDirection="column" border="1px solid" borderColor="gray.200">
                      {/* Chat Header */}
                      <Flex bg="gray.100" p={4} borderBottom="1px solid" borderColor="gray.200" align="center" justify="space-between" borderTopRadius="md">
                        <HStack spacing={3}>
                          <Hash size={20} color="gray.500" />
                          <VStack align="start" spacing={0}>
                            <Text fontWeight="bold" fontSize="md">{selectedChat.project_name || 'Unnamed Project'}</Text>
                            <Text fontSize="xs" color="gray.500">ID: {selectedChat.channel_id}</Text>
                          </VStack>
                        </HStack>
                        <HStack spacing={2}>
                          <Button size="sm" colorScheme="blue" variant="solid" leftIcon={<Play size={14} />}>Start</Button>
                          <Button size="sm" colorScheme="red" variant="solid" leftIcon={<Square size={14} />}>Stop</Button>
                          <Button size="sm" colorScheme="gray" variant="outline" leftIcon={<Settings size={14} />}>Settings</Button>
                        </HStack>
                      </Flex>
                      {/* Chat Messages Area */}
                      <Box flex={1} p={4} overflowY="auto" bg="gray.50">
                        <Text color="gray.500" textAlign="center" mt={10}>No messages to display.</Text>
                      </Box>
                    </Box>
                  ) : (
                    <Box flex={1} bg="gray.50" borderRadius="md" display="flex" alignItems="center" justifyContent="center" p={4}>
                      <Text color="gray.500" m="auto">Select a project to view chat</Text>
                    </Box>
                  )}"""

content = content.replace(old_chat_area, new_chat_area)

# And we need to add selectedChat state.
content = content.replace("const [chats, setChats] = useState<any[]>([]);", "const [chats, setChats] = useState<any[]>([]);\n  const [selectedChat, setSelectedChat] = useState<any>(null);")

# And add onClick to the chat item.
content = content.replace("<Box key={chat.id} p={3} _hover={{ bg: 'gray.100' }} cursor=\"pointer\" borderRadius=\"md\" border=\"1px solid\" borderColor=\"gray.200\">", "<Box key={chat.id} p={3} _hover={{ bg: 'gray.100' }} bg={selectedChat?.id === chat.id ? 'blue.50' : 'transparent'} cursor=\"pointer\" borderRadius=\"md\" border=\"1px solid\" borderColor=\"gray.200\" onClick={() => setSelectedChat(chat)}>")

with open("src/ganymede/web/themes/default/src/App.tsx", "w") as f:
    f.write(content)
