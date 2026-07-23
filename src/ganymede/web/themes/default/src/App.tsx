import { useEffect, useState, useRef } from 'react';
import { Routes, Route, useNavigate, useLocation } from 'react-router-dom';
import { PiRobot, PiGear, PiSquaresFour, PiFolder, PiPlay, PiStop, PiHash, PiDotsThreeOutlineVertical } from 'react-icons/pi';
import {
  Box,
  Flex,
  Text,
  VStack,
  HStack,
  Button,
  Progress,
  Tabs,
  TabList,
  TabPanels,
  Tab,
  TabPanel,
  Input,
  Select,
  Checkbox,
  Textarea,
  Heading,
  Divider,
  Image,
} from '@chakra-ui/react';

export default function App() {
  const navigate = useNavigate();
  const location = useLocation();
  const activeView = location.pathname === '/' ? 'dashboard' : location.pathname.substring(1);
  const [status, setStatus] = useState<any>(null);
  const [logs, setLogs] = useState<any[]>([]);
  const logsEndRef = useRef<HTMLDivElement>(null);
  const [chats, setChats] = useState<any[]>([]);
  const [selectedChat, setSelectedChat] = useState<any>(null);
  const [botsList, setBotsList] = useState<any>({});

  useEffect(() => {
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
          setBotsList(data.payload);
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
    
    fetch('/api/status').then(res => res.json()).then(data => setStatus(data)).catch(err => console.error(err));
    fetch('/api/chats').then(res => res.json()).then(data => { if (data && data.chats) setChats(data.chats); }).catch(err => console.error(err));
    fetch('/api/bots').then(res => res.json()).then(data => { if (data && data.bots) setBotsList(data.bots); }).catch(err => console.error(err));

    return () => ws.close();
  }, []);

  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs]);

  return (
    <Flex h="100vh" flexDirection="column" bg="gray.50" fontFamily="'Inter', sans-serif">
      <Flex bg="#C6A87C" p={2} color="white" alignItems="center" justify="space-between" borderBottom="1px solid rgba(0,0,0,0.1)" shadow="sm">
        <HStack spacing={4}>
          <Image src="/ganymede-logo-light.png" alt="Ganymede Logo" h="28px" />
          <Text fontWeight="bold" fontSize="lg" fontFamily="'Cinzel', serif">Ganymede Gateway</Text>
        </HStack>
        <HStack>
          <Text fontSize="sm">{status?.status === 'online' ? 'Gateway Online' : 'Disconnected'}</Text>
        </HStack>
      </Flex>

      <Flex flex={1} overflow="hidden">
        <Box w="250px" bg="white" borderRight="1px" borderColor="gray.200" p={4}>
          <VStack align="stretch" spacing={4}>
            <Box>
              <Text fontSize="xs" fontWeight="bold" color="gray.500" textTransform="uppercase">Main</Text>
              <Button w="100%" justifyContent="flex-start" leftIcon={<PiSquaresFour size={18} />} variant={activeView === 'dashboard' ? 'solid' : 'ghost'} colorScheme="blue" onClick={() => navigate('/')}>Dashboard</Button>
              <Button w="100%" justifyContent="flex-start" leftIcon={<PiFolder size={18} />} variant={activeView === 'projects' ? 'solid' : 'ghost'} colorScheme="blue" onClick={() => navigate('/projects')}>Projects</Button>
            </Box>
            <Box>
              <Text fontSize="xs" fontWeight="bold" color="gray.500" textTransform="uppercase">Configuration</Text>
              <Button w="100%" justifyContent="flex-start" leftIcon={<PiRobot size={18} />} variant={activeView === 'bots' ? 'solid' : 'ghost'} colorScheme="blue" onClick={() => navigate('/bots')}>Bots</Button>
              <Button w="100%" justifyContent="flex-start" leftIcon={<PiGear size={18} />} variant={activeView === 'settings' ? 'solid' : 'ghost'} colorScheme="blue" onClick={() => navigate('/settings')}>Settings</Button>
            </Box>
          </VStack>
        </Box>

        <Box flex={1} p={6} overflowY="auto">
          <Routes>
            <Route path="/" element={
              <Flex gap={6}>
                <Box w="33%" bg="white" p={4} shadow="sm" borderRadius="md">
                  <Heading size="md" mb={4} fontFamily="'Cinzel', serif">System Metrics</Heading>
                  <HStack justify="space-between" mb={2}>
                    <Text color="gray.500">Active Instances</Text>
                    <Text fontWeight="bold" color="blue.500">{status?.metrics?.active_instances || 0}</Text>
                  </HStack>
                  <Divider my={4} />
                  <Box mb={4}>
                    <HStack justify="space-between" mb={1}>
                      <Text fontSize="sm" color="gray.500">Tokens Streamed</Text>
                      <Text fontSize="sm" fontWeight="bold">{status?.metrics?.tokens_hour || 0} / {status?.metrics?.token_limit || 200000}</Text>
                    </HStack>
                    <Progress size="sm" value={((status?.metrics?.tokens_hour || 0) / (status?.metrics?.token_limit || 200000)) * 100} colorScheme="yellow" />
                  </Box>
                  <Box mb={4}>
                    <HStack justify="space-between" mb={1}>
                      <Text fontSize="sm" color="gray.500">API Requests vs Quota</Text>
                      <Text fontSize="sm" fontWeight="bold">{status?.metrics?.quota_used || 0} / {status?.metrics?.quota_limit || 100}</Text>
                    </HStack>
                    <Progress size="sm" value={((status?.metrics?.quota_used || 0) / (status?.metrics?.quota_limit || 100)) * 100} colorScheme="green" />
                  </Box>
                  <HStack justify="space-between">
                    <Text fontSize="sm" color="gray.500">Global Model Setting</Text>
                    <Text fontSize="sm" fontWeight="bold" color="green.500">{status?.model || 'Default'}</Text>
                  </HStack>
                </Box>
                <Box flex={1} bg="white" p={4} shadow="sm" borderRadius="md" display="flex" flexDirection="column">
                  <HStack justify="space-between" mb={4}>
                    <Heading size="md" fontFamily="'Cinzel', serif">Chalice Telemetry</Heading>
                    <Button size="sm" variant="outline" colorScheme="blue">Export JSON</Button>
                  </HStack>
                  <Box flex={1} overflowY="auto" bg="gray.900" color="green.300" p={4} borderRadius="md" fontFamily="monospace" fontSize="sm">
                    {logs.length === 0 && <Text color="gray.500">Waiting for agent telemetry stream...</Text>}
                    {logs.map((log, i) => (
                      <Box key={i}>
                        <Text as="span" color="gray.500">[{new Date().toLocaleTimeString()}] </Text>
                        <Text as="span" color={log.level === 'error' ? 'red.400' : 'green.300'}>
                          {log.event || JSON.stringify(log)} {log.payload ? `- ${JSON.stringify(log.payload)}` : ''}
                        </Text>
                      </Box>
                    ))}
                    <div ref={logsEndRef} />
                  </Box>
                </Box>
              </Flex>
            } />

            <Route path="/projects" element={
              <Box bg="white" p={6} shadow="sm" borderRadius="md" h="100%" display="flex" flexDirection="column">
                <Heading size="lg" mb={4} fontFamily="'Cinzel', serif">Projects</Heading>
                <Input placeholder="Search channels by name..." mb={4} />
                <Flex flex={1} gap={4} overflow="hidden">
                  <Box w="300px" borderRight="1px" borderColor="gray.200" pr={4} overflowY="auto">
                    <VStack align="stretch">
                      {chats.map(chat => (
                        <Box key={chat.id} p={3} _hover={{ bg: 'gray.100' }} bg={selectedChat?.id === chat.id ? 'blue.50' : 'transparent'} cursor="pointer" borderRadius="md" border="1px solid" borderColor="gray.200" onClick={() => setSelectedChat(chat)}>
                          <HStack justify="space-between">
                            <Text fontWeight="bold">{chat.project_name || `${chat.platform}-${chat.channel_id}`}</Text>
                            <Text fontSize="xs" bg="gray.700" color="white" px={2} borderRadius="full">{chat.msg_count}</Text>
                          </HStack>
                          <Text fontSize="xs" color="gray.500">{chat.actual_conv_id}</Text>
                        </Box>
                      ))}
                      {chats.length === 0 && <Text fontSize="sm" color="gray.500">Loading projects...</Text>}
                    </VStack>
                  </Box>
                  <Box flex={1} display="flex" flexDirection="column">
                    {selectedChat ? (
                      <Box flex={1} bg="white" borderRadius="md" display="flex" flexDirection="column" border="1px solid" borderColor="gray.200">
                        <Flex bg="white" p={4} borderBottom="1px solid" borderColor="gray.200" align="center" justify="space-between" borderTopRadius="md" shadow="sm" zIndex={2}>
                          <HStack spacing={4}>
                            <Flex bg="blue.50" p={2} borderRadius="md">
                              <PiHash size={24} color="#3182CE" />
                            </Flex>
                            <VStack align="start" spacing={0}>
                              <Text fontWeight="bold" fontSize="lg" color="gray.800">{selectedChat.project_name || 'Unnamed Project'}</Text>
                              <Text fontSize="sm" color="gray.500">Channel ID: {selectedChat.channel_id}</Text>
                            </VStack>
                          </HStack>
                          <HStack spacing={3}>
                            <Button size="sm" colorScheme="blue" variant="solid" leftIcon={<PiPlay size={16} />}>Start Engine</Button>
                            <Button size="sm" colorScheme="red" variant="ghost" leftIcon={<PiStop size={16} />}>Halt</Button>
                            <Button size="sm" colorScheme="gray" variant="ghost" leftIcon={<PiGear size={16} />}>Config</Button>
                            <Button size="sm" colorScheme="gray" variant="ghost" px={2}><PiDotsThreeOutlineVertical size={16} /></Button>
                          </HStack>
                        </Flex>
                        <Box flex={1} p={4} overflowY="auto" bg="gray.50">
                          <Text color="gray.500" textAlign="center" mt={10}>No messages to display.</Text>
                        </Box>
                      </Box>
                    ) : (
                      <Box flex={1} bg="gray.50" borderRadius="md" display="flex" alignItems="center" justifyContent="center" p={4}>
                        <Text color="gray.500" m="auto">Select a project to view chat</Text>
                      </Box>
                    )}
                  </Box>
                </Flex>
              </Box>
            } />

            <Route path="/bots" element={
              <Box bg="white" p={6} shadow="sm" borderRadius="md">
                <Heading size="lg" mb={2} fontFamily="'Cinzel', serif">Bots</Heading>
                <Text color="gray.500" mb={6}>Manage connected bot identities and their associated providers.</Text>
                {Object.keys(botsList).length > 0 ? (
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
                )}
              </Box>
            } />

            <Route path="/settings" element={
              <Box bg="white" p={6} shadow="sm" borderRadius="md">
                <Heading size="lg" mb={2} fontFamily="'Cinzel', serif">Settings</Heading>
                <Text color="gray.500" mb={6}>Direct manipulation of Antigravity configuration files.</Text>
                
                <Tabs variant="enclosed" colorScheme="blue">
                  <TabList>
                    <Tab>Global Settings</Tab>
                    <Tab>Rules & Workflows</Tab>
                    <Tab>Raw Config</Tab>
                  </TabList>
                  <TabPanels>
                    <TabPanel>
                      <VStack align="stretch" spacing={4} maxW="600px">
                        <Box>
                          <Text fontSize="sm" fontWeight="bold" mb={1}>Execution Mode</Text>
                          <Select size="sm">
                            <option value="accept-edits">accept-edits</option>
                            <option value="plan">plan</option>
                          </Select>
                        </Box>
                        <Box>
                          <Checkbox size="sm">Skip Permissions (Danger)</Checkbox>
                        </Box>
                        <Box>
                          <Text fontSize="sm" fontWeight="bold" mb={1}>Mission Statement</Text>
                          <Textarea size="sm" placeholder="assisting the user..." />
                        </Box>
                        <Box>
                          <Text fontSize="sm" fontWeight="bold" mb={1}>System Instructions Base</Text>
                          <Textarea size="sm" placeholder="Agent base instructions..." />
                        </Box>
                        <Button colorScheme="blue" size="sm" alignSelf="flex-start">Save Global Settings</Button>
                      </VStack>
                    </TabPanel>
                    <TabPanel>
                      <Text color="gray.500">Manage Antigravity system rules.</Text>
                    </TabPanel>
                    <TabPanel>
                      <Text color="gray.500">Raw Config Editor</Text>
                    </TabPanel>
                  </TabPanels>
                </Tabs>
              </Box>
            } />
          </Routes>
        </Box>
      </Flex>
    </Flex>
  );
}
